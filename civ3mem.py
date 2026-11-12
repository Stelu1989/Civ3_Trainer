"""Memory access layer for Civilization III: Conquests (Steam v1.22, with or without C3X).

All addresses below are for the Steam build of Civ3Conquests.exe. They come from the
C3X project's reverse-engineering notes (github.com/maxpetul/C3X, source/civ_prog_objects.csv
and source/Civ3Conquests.h) and were cross-checked against the game's own machine code.
The exe has no ASLR (image base 0x400000), so these are absolute addresses.
"""

import ctypes
import ctypes.wintypes as wt
import struct

# --------------------------------------------------------------------------------------
# Win32 plumbing
# --------------------------------------------------------------------------------------

PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x00000002
STILL_ACTIVE = 259

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
kernel32.ReadProcessMemory.argtypes = [wt.HANDLE, wt.LPCVOID, wt.LPVOID, ctypes.c_size_t,
                                       ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.argtypes = [wt.HANDLE, wt.LPVOID, wt.LPCVOID, ctypes.c_size_t,
                                        ctypes.POINTER(ctypes.c_size_t)]


class MemoryError_(Exception):
    pass


def find_process(names=("civ3conquests.exe",)):
    """Return the PID of the first running process whose exe name matches, or None."""
    names = {n.lower() for n in names}
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (None, wt.HANDLE(-1).value):
        return None
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() in names:
                return entry.th32ProcessID
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return None


class Process:
    def __init__(self, pid):
        self.pid = pid
        access = PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_QUERY_INFORMATION
        self.handle = kernel32.OpenProcess(access, False, pid)
        if not self.handle:
            raise MemoryError_(f"OpenProcess failed (error {ctypes.get_last_error()}). "
                               "Try running the trainer as administrator.")

    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def alive(self):
        code = wt.DWORD()
        return bool(self.handle) and kernel32.GetExitCodeProcess(self.handle, ctypes.byref(code)) \
            and code.value == STILL_ACTIVE

    def read(self, addr, size):
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        if not kernel32.ReadProcessMemory(self.handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)) \
                or got.value != size:
            raise MemoryError_(f"read of {size} bytes at {addr:#x} failed (error {ctypes.get_last_error()})")
        return buf.raw

    def write(self, addr, data):
        got = ctypes.c_size_t()
        if not kernel32.WriteProcessMemory(self.handle, ctypes.c_void_p(addr), data, len(data), ctypes.byref(got)) \
                or got.value != len(data):
            raise MemoryError_(f"write of {len(data)} bytes at {addr:#x} failed (error {ctypes.get_last_error()})")

    def i32(self, addr):
        return struct.unpack("<i", self.read(addr, 4))[0]

    def u32(self, addr):
        return struct.unpack("<I", self.read(addr, 4))[0]

    def set_i32(self, addr, value):
        self.write(addr, struct.pack("<i", value))

    def set_u32(self, addr, value):
        self.write(addr, struct.pack("<I", value & 0xFFFFFFFF))

    def cstr(self, addr, size):
        raw = self.read(addr, size).split(b"\0", 1)[0]
        return raw.decode("latin-1")


# --------------------------------------------------------------------------------------
# Game layout (Steam v1.22)
# --------------------------------------------------------------------------------------

# First bytes of Leader_has_tech (0x56D5A0). Used to confirm this is the Steam 1.22 exe.
SIGNATURE_ADDR = 0x56D5A0
SIGNATURE = bytes.fromhex("8b44240483f8ff7505b001c204003b05bc659e00")

ADDR_BIC = 0x9E5D08              # BIC struct (scenario/rules data), static
ADDR_LEADERS = 0xA75698          # Leader leaders[32], static array
ADDR_HUMAN_PLAYER_BITS = 0xA74EB4  # int: bit N set => civ N is human
ADDR_PLAYER_BITS = 0xA74EB8      # unsigned: bit N set => civ N is in the game; 0 = no game running
ADDR_CURRENT_TURN = 0xA74EA4     # int: current turn number

ADDR_CITIES = 0xA75668          # Cities list: {vtable, CityItem *items, ?, ?, LastIndex, Capacity}
ADDR_UNITS = 0xA75680           # Units list, same layout; items are {int, Body *}
ADDR_GAME_FLAGS = 0xA74E74      # bit 0x200 halves production costs
ADDR_DIFFICULTY = 0xA74E7C      # difficulty level index

MAX_CIVS = 32

# City (pointer = list body pointer - 0x1C)
C_CIV = 0x28                    # byte
C_STORED_FOOD = 0x40
C_STORED_SHIELDS = 0x44
C_ORDER_ID = 0x4C
C_ORDER_TYPE = 0x50             # 1 = improvement, 2 = unit
C_SIZE = 0x138
C_NAME = 0x1E0                  # char[20]
C_FOOD_REQUIRED = 0x244         # size of the food box

# Unit (pointer = list body pointer - 0x1C)
U_CIV = 0x34
U_TYPE = 0x40
U_MOVES = 0x50                  # movement points used this turn

# BIC rule tables
BIC_IMPROVEMENTS_PTR = 0xBA4
IMPROVEMENT_STRIDE = 0x110
IMPROVEMENT_COST = 0x94
IMPROVEMENT_FLAGS = 0xEC          # bit 0: cost scales with city count (Palace)
IMPROVEMENT_CHARACTERISTICS = 0xF0
IMPR_GREAT_WONDER = 0x4
IMPR_SMALL_WONDER = 0x8
# (race bonus bit, improvement characteristic) pairs that halve the cost
TRAIT_HALF_COST = ((0, 0x2), (4, 0x100), (6, 0x400), (7, 0x800), (3, 0x20))
RACE_STRIDE = 0x974
RACE_BONUSES = 0x948
ADDR_WORLD_SIZE_INDEX = 0x9E9BA0
ADDR_WORLD_SIZES_PTR = 0x9E9B30
WORLD_SIZE_STRIDE = 0x54
WORLD_SIZE_OPTIMAL_CITIES = 0x4
BIC_DIFFICULTY_PTR = 0xBB8
DIFFICULTY_STRIDE = 0x7C
DIFFICULTY_COST_FACTOR = 0x68
BIC_UNIT_TYPES_PTR = 0x3CD8
UNIT_TYPE_STRIDE = 0x138
UNIT_TYPE_COST = 0x54

GOLDEN_AGE_TURNS = 20

# BIC offsets
BIC_ADVANCE_COUNT = 0x8B4
BIC_GENERAL = 0x3CDC             # start of the embedded General struct; Advances ptr is after it
BIC_RACES_PTR = 0x3CC8           # Race * (one per civilization type)
RACE_PEDIA = 0x54                # "RACE_..." civilopedia key
RACE_COUNTRY_NAME = 0x9C         # e.g. "Arabia"
ADVANCE_NAME = 0x04
ADVANCE_COST = 0x44
ADVANCE_ERA = 0x48

# Leader offsets
L_VTABLE = 0x00
L_ID = 0x1C
L_RACE_ID = 0x20
L_CAPITAL_ID = 0x2C
L_GOLDEN_AGE_END = 0x3C
L_GOLD_DECREMENT = 0x44
L_GOLD_ENCODED = 0x48
L_GOVERNMENT = 0xA0
L_ERA = 0xF4
L_RESEARCH_BULBS = 0xF8
L_CURRENT_RESEARCH_ID = 0xFC
L_CURRENT_RESEARCH_TURNS = 0x100  # turns already spent on the current tech (counts up)
RESEARCH_TURNS_SPENT = 100         # above Civ3's min (4) and max (50) research time
L_UNIT_COUNT = 0x18C
L_CITIES_COUNT = 0x194

GOLD_MAX = 999_999_999


class Civ3:
    """High-level view of a running Civ3 Conquests game."""

    def __init__(self, proc):
        self.p = proc
        sig = proc.read(SIGNATURE_ADDR, len(SIGNATURE))
        if sig != SIGNATURE:
            raise MemoryError_("Unsupported Civ3Conquests.exe version (expected Steam v1.22).")
        self._leader_size = None
        self._advances = None      # (ptr, stride)
        self._race_stride = None

    # ---------------- discovery ----------------

    def leader_size(self):
        """Find sizeof(Leader) by locating leaders[1] (same vtable, ID == 1)."""
        if self._leader_size:
            return self._leader_size
        blob = self.p.read(ADDR_LEADERS, 0x8000)
        vt0, id0 = struct.unpack_from("<I", blob, L_VTABLE)[0], struct.unpack_from("<i", blob, L_ID)[0]
        if vt0 == 0 or id0 != 0:
            raise MemoryError_("No game loaded yet (leader table is empty).")
        for size in range(0x1000, 0x8000 - 0x20, 4):
            if struct.unpack_from("<I", blob, size)[0] == vt0 and struct.unpack_from("<i", blob, size + L_ID)[0] == 1:
                # double-check with leaders[2]
                if self.p.u32(ADDR_LEADERS + 2 * size) == vt0 and self.p.i32(ADDR_LEADERS + 2 * size + L_ID) == 2:
                    self._leader_size = size
                    return size
        raise MemoryError_("Could not determine Leader struct size.")

    def advances(self):
        """Locate the BIC Advances array: returns (pointer, stride) or None."""
        if self._advances:
            return self._advances
        count = self.advance_count()
        if not 1 <= count <= 1000:
            return None
        blob = self.p.read(ADDR_BIC + BIC_GENERAL, 0x400)
        for off in range(0, len(blob), 4):
            ptr = struct.unpack_from("<I", blob, off)[0]
            if ptr < 0x10000 or ptr > 0x7FFF0000:
                continue
            try:
                head = self.p.read(ptr, 0x200)
            except MemoryError_:
                continue
            for stride in (0x74, 0x78, 0x70):
                names = [head[i * stride + ADVANCE_NAME:i * stride + ADVANCE_NAME + 32].split(b"\0", 1)[0]
                         for i in range(min(3, count))]
                if all(_looks_like_name(n) for n in names):
                    self._advances = (ptr, stride)
                    return self._advances
        return None

    # ---------------- game-wide ----------------

    def game_loaded(self):
        """True while a game is in progress. Player bits are 0 in the main menu (as C3X relies on)."""
        if self.p.u32(ADDR_PLAYER_BITS) == 0:
            return False
        try:
            self.leader_size()
            return True
        except MemoryError_:
            return False

    def current_turn(self):
        return self.p.i32(ADDR_CURRENT_TURN)

    def human_bits(self):
        return self.p.u32(ADDR_HUMAN_PLAYER_BITS)

    def human_civ(self):
        bits = self.human_bits()
        for i in range(1, MAX_CIVS):  # civ 0 is the barbarians
            if bits & (1 << i):
                return i
        return None

    def advance_count(self):
        return self.p.i32(ADDR_BIC + BIC_ADVANCE_COUNT)

    def tech_name(self, tech_id):
        if tech_id is None or tech_id < 0:
            return "(none)"
        adv = self.advances()
        if adv and tech_id < self.advance_count():
            ptr, stride = adv
            return self.p.cstr(ptr + tech_id * stride + ADVANCE_NAME, 32) or f"Tech #{tech_id}"
        return f"Tech #{tech_id}"

    def tech_base_cost(self, tech_id):
        adv = self.advances()
        if adv and 0 <= tech_id < self.advance_count():
            return self.p.i32(adv[0] + tech_id * adv[1] + ADVANCE_COST)
        return None

    def civ_name(self, civ):
        """Country name (e.g. 'Arabia') from the BIC Races table, found via the leader's RaceID."""
        try:
            races = self.p.u32(ADDR_BIC + BIC_RACES_PTR)
            if self._race_stride is None:
                blob = self.p.read(races, 0x4000)
                vt = blob[:4]
                self._race_stride = next(o for o in range(4, len(blob) - 0x60, 4)
                                         if blob[o:o + 4] == vt and blob[o + RACE_PEDIA:o + RACE_PEDIA + 5] == b"RACE_")
            race_id = self.p.i32(self.leader_addr(civ) + L_RACE_ID)
            name = self.p.cstr(races + race_id * self._race_stride + RACE_COUNTRY_NAME, 40)
            return name or f"Civ {civ}"
        except (MemoryError_, StopIteration):
            return f"Civ {civ}"

    def tech_names(self):
        return [self.tech_name(i) for i in range(self.advance_count())]

    # ---------------- per civ ----------------

    def leader_addr(self, civ):
        return ADDR_LEADERS + civ * self.leader_size()

    def civ_exists(self, civ):
        a = self.leader_addr(civ)
        return self.p.i32(a + L_ID) == civ and (self.p.i32(a + L_CITIES_COUNT) > 0 or self.p.i32(a + L_UNIT_COUNT) > 0)

    def gold(self, civ):
        a = self.leader_addr(civ)
        return self.p.i32(a + L_GOLD_ENCODED) + self.p.i32(a + L_GOLD_DECREMENT)

    def set_gold(self, civ, amount):
        amount = max(0, min(GOLD_MAX, int(amount)))
        a = self.leader_addr(civ)
        dec = self.p.i32(a + L_GOLD_DECREMENT)
        self.p.set_i32(a + L_GOLD_ENCODED, amount - dec)

    def research(self, civ):
        a = self.leader_addr(civ)
        return {
            "tech_id": self.p.i32(a + L_CURRENT_RESEARCH_ID),
            "bulbs": self.p.i32(a + L_RESEARCH_BULBS),
            "turns": self.p.i32(a + L_CURRENT_RESEARCH_TURNS),
        }

    def set_bulbs(self, civ, bulbs):
        self.p.set_i32(self.leader_addr(civ) + L_RESEARCH_BULBS, int(bulbs))

    def complete_research(self, civ, bulbs):
        """Make the current tech complete at the end of this turn.

        Civ3 enforces a minimum research time (default 4 turns): a tech can't finish until
        Current_Research_Turns (turns already spent on it) reaches that minimum, no matter how
        many beakers are stored. So we fill the beakers AND mark plenty of turns as spent.
        """
        a = self.leader_addr(civ)
        self.p.set_i32(a + L_RESEARCH_BULBS, int(bulbs))
        self.p.set_i32(a + L_CURRENT_RESEARCH_TURNS, RESEARCH_TURNS_SPENT)

    # ---------------- golden age ----------------

    def golden_age_turns_left(self, civ):
        return max(0, self.p.i32(self.leader_addr(civ) + L_GOLDEN_AGE_END) - self.current_turn())

    def extend_golden_age(self, civ, turns=GOLDEN_AGE_TURNS):
        """Start a golden age, or extend the running one, by `turns` turns."""
        end = self.current_turn() + self.golden_age_turns_left(civ) + turns
        self.p.set_i32(self.leader_addr(civ) + L_GOLDEN_AGE_END, end)

    # ---------------- cities ----------------

    def _list(self, addr):
        """Object pointers from one of the game's Cities/Units lists (skipping empty slots)."""
        items, last = self.p.u32(addr + 4), self.p.i32(addr + 0x10)
        if not items or last < 0:
            return []
        raw = self.p.read(items, (last + 1) * 8)
        bodies = struct.unpack_from(f"<{2 * (last + 1)}I", raw)[1::2]
        return [b - 0x1C for b in bodies if b]

    def cities(self, civ):
        return [c for c in self._list(ADDR_CITIES) if self.p.read(c + C_CIV, 1)[0] == civ]

    def city_name(self, city):
        return self.p.cstr(city + C_NAME, 20)

    def _cost_factor(self, civ):
        if self.human_bits() & (1 << civ):
            factor = 10
        else:
            diff = self.p.i32(ADDR_DIFFICULTY)
            factor = self.p.i32(self.p.u32(ADDR_BIC + BIC_DIFFICULTY_PTR) + diff * DIFFICULTY_STRIDE + DIFFICULTY_COST_FACTOR)
        if self.p.u32(ADDR_GAME_FLAGS) & 0x200:
            factor = int(factor / 2)
        return max(1, factor)

    def order_cost(self, city):
        """Shields needed for the city's current build.

        Mirrors City_get_order_cost (0x4B3D30), which calls the unit cost function (0x5766B0)
        or the improvement cost function (0x576480).
        """
        civ = self.p.read(city + C_CIV, 1)[0]
        order_id, order_type = self.p.i32(city + C_ORDER_ID), self.p.i32(city + C_ORDER_TYPE)
        factor = self._cost_factor(civ)
        if order_type == 2:
            base = self.p.i32(self.p.u32(ADDR_BIC + BIC_UNIT_TYPES_PTR) + order_id * UNIT_TYPE_STRIDE + UNIT_TYPE_COST)
            return max(1, int(factor * base / 10))
        if order_type != 1:
            return None

        impr = self.p.u32(ADDR_BIC + BIC_IMPROVEMENTS_PTR) + order_id * IMPROVEMENT_STRIDE
        cost = factor * self.p.i32(impr + IMPROVEMENT_COST)
        chars = self.p.u32(impr + IMPROVEMENT_CHARACTERISTICS)
        if not chars & (IMPR_GREAT_WONDER | IMPR_SMALL_WONDER):
            # Buildings tied to a civ trait cost half for civs with that trait.
            race = self.p.u32(ADDR_BIC + BIC_RACES_PTR) + self.p.i32(self.leader_addr(civ) + L_RACE_ID) * RACE_STRIDE
            bonuses = self.p.u32(race + RACE_BONUSES)
            if any(bonuses & (1 << bonus) and chars & flag for bonus, flag in TRAIT_HALF_COST):
                cost = int(cost / 2)
        if self.p.u32(impr + IMPROVEMENT_FLAGS) & 1:
            # Palace-like buildings scale with the number of cities vs. the map's optimal count.
            ws = self.p.i32(ADDR_WORLD_SIZE_INDEX)
            optimal = self.p.i32(self.p.u32(ADDR_WORLD_SIZES_PTR) + ws * WORLD_SIZE_STRIDE + WORLD_SIZE_OPTIMAL_CITIES)
            cities = self.p.i32(self.leader_addr(civ) + L_CITIES_COUNT)
            cost *= min(10, max(3, int(6 * cities / optimal))) if optimal else 3
        return max(1, cost)

    def finish_city_production(self, city):
        """Fill one city's shield box so its current build completes at end of turn. True if changed."""
        cost = self.order_cost(city)
        if cost and self.p.i32(city + C_STORED_SHIELDS) < cost:
            self.p.set_i32(city + C_STORED_SHIELDS, cost)
            return True
        return False

    def fill_city_food(self, city):
        """Fill one city's food box so it grows by one at end of turn (if allowed to grow). True if changed."""
        need = self.p.i32(city + C_FOOD_REQUIRED)
        if need > 0 and self.p.i32(city + C_STORED_FOOD) < need:
            self.p.set_i32(city + C_STORED_FOOD, need)
            return True
        return False

    def finish_production(self, civ):
        """Finish production in all of a civ's cities. Returns the number of cities changed."""
        return sum(self.finish_city_production(c) for c in self.cities(civ))

    def fill_food(self, civ):
        """Fill the food box in all of a civ's cities. Returns the number of cities changed."""
        return sum(self.fill_city_food(c) for c in self.cities(civ))

    # ---------------- units ----------------

    def units(self, civ):
        return [u for u in self._list(ADDR_UNITS) if self.p.i32(u + U_CIV) == civ]

    def restore_moves(self, civ):
        """Give all of a civ's units full movement. Returns the number of units changed."""
        done = 0
        for u in self.units(civ):
            if self.p.i32(u + U_MOVES) != 0:
                self.p.set_i32(u + U_MOVES, 0)
                done += 1
        return done


def _looks_like_name(b):
    return 2 <= len(b) < 32 and all(32 <= c < 127 for c in b)


def attach():
    """Find and attach to the game. Returns a Civ3 instance or raises MemoryError_."""
    pid = find_process()
    if pid is None:
        raise MemoryError_("Civ3Conquests.exe is not running.")
    return Civ3(Process(pid))
