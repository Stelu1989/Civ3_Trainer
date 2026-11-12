"""Civilization III: Conquests trainer (Steam v1.22, single player).

Run:  python civ3_trainer.py          -> GUI
      python civ3_trainer.py --dump   -> print what the trainer sees (diagnostics)
"""

import sys
import tkinter as tk
from tkinter import ttk, messagebox

import civ3mem
from civ3mem import MemoryError_

# Beakers written by "Complete research". Far above any real tech cost; the game
# discards leftover beakers when the tech completes.
COMPLETE_RESEARCH_BULBS = 1_000_000
REFRESH_MS = 1000
PAD = {"padx": 6, "pady": 3}


class TrainerApp:
    def __init__(self, root):
        self.root = root
        self.game = None
        self.civ_ids = []
        self.city_ptrs = []
        root.title("Civ3 Conquests Trainer")
        root.resizable(False, False)

        frm = ttk.Frame(root, padding=10)
        frm.grid()

        # --- status / player ---
        self.status = tk.StringVar(value="Looking for Civ3Conquests.exe ...")
        ttk.Label(frm, textvariable=self.status, foreground="#555").grid(row=0, column=0, columnspan=2, sticky="w", **PAD)
        top = ttk.Frame(frm)
        top.grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(top, text="Civilization:").grid(row=0, column=0, sticky="w", **PAD)
        self.civ_var = tk.StringVar()
        self.civ_box = ttk.Combobox(top, textvariable=self.civ_var, state="readonly", width=28)
        self.civ_box.grid(row=0, column=1, sticky="w", **PAD)

        left = ttk.Frame(frm)
        left.grid(row=2, column=0, sticky="n")
        right = ttk.Frame(frm)
        right.grid(row=2, column=1, sticky="n", padx=(10, 0))

        self.build_gold(left)
        self.build_research(left)
        self.build_cities(right)
        self.build_units(right)
        self.build_golden_age(right)

        self.root.after(100, self.tick)

    # ---------------- layout ----------------

    def section(self, parent, title):
        box = ttk.LabelFrame(parent, text=title, padding=8)
        box.pack(fill="x", pady=5)
        return box

    def build_gold(self, parent):
        gold = self.section(parent, "Gold")
        self.gold_now = tk.StringVar(value="-")
        ttk.Label(gold, text="Treasury:").grid(row=0, column=0, sticky="w", **PAD)
        ttk.Label(gold, textvariable=self.gold_now, font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="w", **PAD)
        ttk.Button(gold, text="+1,000", command=lambda: self.add_gold(1000)).grid(row=0, column=2, **PAD)
        ttk.Button(gold, text="+10,000", command=lambda: self.add_gold(10000)).grid(row=0, column=3, **PAD)
        ttk.Label(gold, text="Set to:").grid(row=1, column=0, sticky="w", **PAD)
        self.gold_entry = ttk.Entry(gold, width=12)
        self.gold_entry.insert(0, "50000")
        self.gold_entry.grid(row=1, column=1, sticky="w", **PAD)
        ttk.Button(gold, text="Set", command=self.set_gold).grid(row=1, column=2, **PAD)
        self.lock_gold = tk.BooleanVar()
        ttk.Checkbutton(gold, text="Lock", variable=self.lock_gold).grid(row=1, column=3, sticky="w", **PAD)

    def build_research(self, parent):
        res = self.section(parent, "Research")
        self.res_now = tk.StringVar(value="-")
        self.res_bulbs = tk.StringVar(value="-")
        ttk.Label(res, text="Researching:").grid(row=0, column=0, sticky="w", **PAD)
        ttk.Label(res, textvariable=self.res_now, font=("Segoe UI", 10, "bold")).grid(row=0, column=1, columnspan=2, sticky="w", **PAD)
        ttk.Label(res, text="Beakers:").grid(row=1, column=0, sticky="w", **PAD)
        ttk.Label(res, textvariable=self.res_bulbs).grid(row=1, column=1, columnspan=2, sticky="w", **PAD)
        ttk.Button(res, text="Complete research (at end of turn)", command=self.complete_research) \
            .grid(row=2, column=0, columnspan=3, sticky="we", **PAD)

    def build_cities(self, parent):
        box = self.section(parent, "Cities")
        self.cities_info = tk.StringVar(value="-")
        ttk.Label(box, textvariable=self.cities_info).pack(anchor="w", **PAD)

        # single city
        one = ttk.Frame(box)
        one.pack(fill="x")
        self.city_var = tk.StringVar()
        self.city_box = ttk.Combobox(one, textvariable=self.city_var, state="readonly", width=34)
        self.city_box.pack(fill="x", **PAD)
        self.city_box.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        row = ttk.Frame(one)
        row.pack(fill="x")
        ttk.Button(row, text="Finish production", command=lambda: self.city_action(
            self.game.finish_city_production, "production will finish", "already has enough shields")) \
            .pack(side="left", expand=True, fill="x", **PAD)
        ttk.Button(row, text="Fill food box", command=lambda: self.city_action(
            self.game.fill_city_food, "will grow", "food box is already full")) \
            .pack(side="left", expand=True, fill="x", **PAD)

        ttk.Separator(box).pack(fill="x", pady=6)
        ttk.Label(box, text="All cities:").pack(anchor="w", **PAD)
        ttk.Button(box, text="Finish production in all cities (end of turn)",
                   command=lambda: self.report(lambda: f"Filled the shield box in {self.game.finish_production(self.civ())} cities.")) \
            .pack(fill="x", **PAD)
        ttk.Button(box, text="Fill food boxes: all cities grow +1 (end of turn)",
                   command=lambda: self.report(lambda: f"Filled the food box in {self.game.fill_food(self.civ())} cities.\n"
                                                       "Cities at their size limit (aqueduct/hospital) won't grow.")) \
            .pack(fill="x", **PAD)

    def build_units(self, parent):
        box = self.section(parent, "Units")
        self.units_info = tk.StringVar(value="-")
        ttk.Label(box, textvariable=self.units_info).pack(anchor="w", **PAD)
        ttk.Button(box, text="Full movement for all units", command=lambda: self.report(
            lambda: f"Restored movement for {self.game.restore_moves(self.civ())} units.")).pack(fill="x", **PAD)

    def build_golden_age(self, parent):
        box = self.section(parent, "Golden age")
        self.ga_info = tk.StringVar(value="-")
        ttk.Label(box, textvariable=self.ga_info).pack(anchor="w", **PAD)
        ttk.Button(box, text=f"Start / extend golden age (+{civ3mem.GOLDEN_AGE_TURNS} turns)",
                   command=lambda: self.guarded(lambda: self.game.extend_golden_age(self.civ()))).pack(fill="x", **PAD)

    # ---------------- helpers ----------------

    def civ(self):
        idx = self.civ_box.current()
        return self.civ_ids[idx] if 0 <= idx < len(self.civ_ids) else None

    def guarded(self, fn):
        if self.game is None or self.civ() is None:
            messagebox.showerror("Civ3 Trainer", "No game attached.")
            return None
        try:
            return fn()
        except MemoryError_ as e:
            messagebox.showerror("Civ3 Trainer", str(e))
        finally:
            self.refresh()

    def report(self, fn):
        msg = self.guarded(fn)
        if msg:
            self.status.set(msg.splitlines()[0])
            if "\n" in msg:
                messagebox.showinfo("Civ3 Trainer", msg)

    # ---------------- actions ----------------

    def add_gold(self, n):
        self.guarded(lambda: self.game.set_gold(self.civ(), self.game.gold(self.civ()) + n))

    def set_gold(self):
        try:
            value = int(self.gold_entry.get().replace(",", "").replace(".", ""))
        except ValueError:
            messagebox.showerror("Civ3 Trainer", "Enter a whole number.")
            return
        self.guarded(lambda: self.game.set_gold(self.civ(), value))

    def complete_research(self):
        def go():
            if self.game.research(self.civ())["tech_id"] < 0:
                raise MemoryError_("Nothing is being researched. Pick a tech in the game first.")
            self.game.complete_research(self.civ(), COMPLETE_RESEARCH_BULBS)
        self.guarded(go)

    def selected_city(self):
        idx = self.city_box.current()
        return self.city_ptrs[idx] if 0 <= idx < len(self.city_ptrs) else None

    def city_action(self, fn, done_text, skip_text):
        city = self.selected_city()
        if city is None:
            messagebox.showinfo("Civ3 Trainer", "Pick a city first.")
            return
        def go():
            name = self.game.city_name(city)
            return f"{name}: {done_text} at end of turn." if fn(city) else f"{name}: {skip_text}."
        self.report(go)

    # ---------------- refresh loop ----------------

    def tick(self):
        try:
            if self.game is None or not self.game.p.alive():
                self.game = None
                self.game = civ3mem.attach()
                self.civ_ids = []
            if not self.game.game_loaded():
                self.status.set("Attached. Waiting for a game to be started or loaded ...")
                self.civ_ids = []
            else:
                self.refresh_civ_list()
                if self.lock_gold.get() and self.civ() is not None:
                    try:
                        target = int(self.gold_entry.get().replace(",", ""))
                        if self.game.gold(self.civ()) != target:
                            self.game.set_gold(self.civ(), target)
                    except ValueError:
                        pass
                self.refresh()
        except MemoryError_ as e:
            self.status.set(str(e))
            if self.game and not self.game.p.alive():
                self.game = None
        self.root.after(REFRESH_MS, self.tick)

    def refresh_civ_list(self):
        g = self.game
        human = g.human_civ()
        ids = [c for c in range(1, civ3mem.MAX_CIVS) if c == human or g.civ_exists(c)]
        if ids != self.civ_ids:
            prev = self.civ()
            self.civ_ids = ids
            self.civ_box["values"] = [f"{g.civ_name(c)}" + ("  (you)" if c == human else "") for c in ids]
            sel = prev if prev in ids else human if human in ids else ids[0] if ids else None
            if sel is not None:
                self.civ_box.current(ids.index(sel))

    def refresh_city_list(self, civ):
        """Rebuild the city picker (sorted by name), keeping the current selection."""
        g = self.game
        prev = self.selected_city()
        cities = sorted(g.cities(civ), key=g.city_name)
        labels = []
        for c in cities:
            cost = g.order_cost(c)
            labels.append(f"{g.city_name(c)}  (size {g.p.i32(c + civ3mem.C_SIZE)}, "
                          f"food {g.p.i32(c + civ3mem.C_STORED_FOOD)}/{g.p.i32(c + civ3mem.C_FOOD_REQUIRED)}, "
                          f"shields {g.p.i32(c + civ3mem.C_STORED_SHIELDS)}/{cost if cost else '-'})")
        self.city_ptrs = cities
        if list(self.city_box["values"]) != labels:
            self.city_box["values"] = labels
        if prev in cities:
            self.city_box.current(cities.index(prev))
        elif cities:
            self.city_box.current(0)
        else:
            self.city_var.set("")

    def refresh(self):
        g, civ = self.game, self.civ()
        if g is None or civ is None:
            return
        try:
            self.status.set(f"Attached to PID {g.p.pid}  -  turn {g.current_turn()}")
            self.gold_now.set(f"{g.gold(civ):,}")
            r = g.research(civ)
            self.res_now.set(g.tech_name(r["tech_id"]))
            self.res_bulbs.set(f"{r['bulbs']:,}   (turns spent: {r['turns']})")
            self.cities_info.set(f"{g.p.i32(g.leader_addr(civ) + civ3mem.L_CITIES_COUNT)} cities")
            self.refresh_city_list(civ)
            self.units_info.set(f"{g.p.i32(g.leader_addr(civ) + civ3mem.L_UNIT_COUNT)} units")
            left = g.golden_age_turns_left(civ)
            self.ga_info.set(f"Active: {left} turns left" if left else "Not active")
        except MemoryError_ as e:
            self.status.set(str(e))


def dump():
    g = civ3mem.attach()
    print(f"PID {g.p.pid}, signature OK")
    print(f"Leader size: {g.leader_size():#x}")
    print(f"Turn: {g.current_turn()}, human bits: {g.human_bits():#x}, human civ: {g.human_civ()}")
    adv = g.advances()
    print(f"Advances: count={g.advance_count()} at {adv[0]:#x} stride {adv[1]:#x}" if adv else "Advances: not found")
    for c in range(civ3mem.MAX_CIVS):
        if c == 0 or g.civ_exists(c):
            r = g.research(c)
            print(f"  civ {c:2} {g.civ_name(c):<12}: gold={g.gold(c):>8}  research={g.tech_name(r['tech_id'])!r} "
                  f"bulbs={r['bulbs']} turns={r['turns']}  golden age left={g.golden_age_turns_left(c)}")
    me = g.human_civ()
    if me is not None:
        print(f"Your cities ({g.civ_name(me)}):")
        for c in g.cities(me):
            print(f"  {g.city_name(c):<16} size {g.p.i32(c + civ3mem.C_SIZE):>2}  "
                  f"food {g.p.i32(c + civ3mem.C_STORED_FOOD)}/{g.p.i32(c + civ3mem.C_FOOD_REQUIRED)}  "
                  f"shields {g.p.i32(c + civ3mem.C_STORED_SHIELDS)}/{g.order_cost(c)}")


def main():
    if "--dump" in sys.argv:
        dump()
        return
    root = tk.Tk()
    TrainerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
