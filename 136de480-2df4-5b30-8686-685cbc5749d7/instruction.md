# Static timing analysis for our standard-cell library

Our team designs chips with an in-house standard-cell library, and we have no timing tool for it. We need one that reads our files and tells us, for every flip-flop, latch, and output, how much timing margin is left. Please build it.

`/app/design/` and `/app/design/example/` each hold a design written for this library: a Liberty file with NLDM tables (`cells.nldm`), a structural Verilog netlist (`top.v`), and SDC constraints (`top.sdc`). Use them to test your parser. They come with no reports or expected results, and they are never graded.

## What to deliver

**D1:** `/app/out/136de480-2df4-5b30-8686-685cbc5749d7_D1_sta.py`, a Python 3.13 program that uses only the standard library.

Run it as `python3 <D1> --lib L --netlist N --sdc S --out R`. It reads library `L`, netlist `N`, and constraints `S`, writes the timing report to `R`, and exits 0.

We grade it only on hidden libraries, netlists, and constraints written in the same subset as the samples. Each run must finish within 20 s.

## Standards it follows

D1 does graph-based static timing analysis under Liberty NLDM and SDC 2.1:

- Liberty NLDM: table lookup through `lu_table_template`, `timing_sense`, `timing_type`, `wire_load`, and the `ff` and `latch` groups.
- SDC 2.1: clock definition, generated and propagated clocks, I/O constraints, `set_multicycle_path` and `set_false_path` with their default edge relationships and default hold check, and `set_timing_derate`.

The inputs use only this subset:

- **Liberty:** the library attributes `time_unit`, `capacitive_load_unit`, and `default_wire_load`. The groups `lu_table_template`, `wire_load` (`capacitance`, `slope`, `fanout_length`), `cell`, `pin` (`direction`, `capacitance`, `clock`, `function`), `ff`, `latch`, and `timing`. A `timing` group uses `related_pin`, `timing_sense`, and `timing_type`. The type is `combinational` when it is missing, or one of `rising_edge`, `setup_rising`, `hold_rising`, `setup_falling`, and `hold_falling`. Its tables are `cell_rise`, `cell_fall`, `rise_transition`, `fall_transition`, `rise_constraint`, and `fall_constraint`.
- **Verilog:** one module with `input`, `output`, and `wire` declarations, named-port instances, and `assign port = net`.
- **SDC:**
  - Commands: `set_units`, `create_clock`, `create_generated_clock` (with `-source` and one of `-divide_by`, `-multiply_by`, or `-edges`), `set_propagated_clock`, `set_clock_transition`, `set_input_transition`, `set_input_delay`, `set_output_delay`, `set_load`, `set_multicycle_path`, `set_false_path`, and `set_timing_derate`.
  - Object queries: `get_ports`, `get_pins`, `get_cells`, `get_clocks`, and `all_clocks`.

The standards leave some choices open. These rules settle them.

## Rules

1. **Units.** Library values are in the library's `time_unit` and `capacitive_load_unit`. SDC values are in the units its `set_units` declares. Report every time in ns.
2. **Table lookup and loads.**
   - Look up a table by linear interpolation in each variable, in the order the template declares the variables.
   - Outside the index range, extend the line through the two nearest breakpoints. An axis with one breakpoint is constant.
   - A net's load is the sum of the `capacitance` of every input pin it drives, the `set_load` of every output port it drives, and the `default_wire_load` capacitance at its fanout. Fanout counts the driven pins plus the output ports.
   - Nets add no delay.
3. **Propagation.**
   - At a pin, the late arrival and late slew are the largest over the arcs into the pin. The early arrival and early slew are the smallest. Each arc uses the input slew of its own analysis (late or early) and the load of the output net.
   - Keep data arrivals apart for each pin, transition, launching clock edge, and exception state. Together, the launching clock, its edge, and the exception state form a launch group. Arrivals merge only within one launch group.
   - An ideal clock has zero latency and its `set_clock_transition` slew at every sequential clock pin.
   - A propagated clock starts at its source port at time 0, with that port's `set_input_transition` slew. It travels through the clock network up to the sequential clock pins. The clock network is every pin reached from a clock source through combinational arcs.
   - A generated clock's source is the register output it is defined on (for example `udiv0/Q`). That output belongs to the clock network: it carries clock arrivals only and does not appear in `arrivals`. Its latency is the master clock's propagated arrival at the register's clock pin plus the register's clock-to-output arc. The register's D pin is still a data endpoint.
   - Input delays launch at the rising edge of their clock. Output delays capture at the rising edge of their clock, with no clock latency.
4. **On-chip variation.** `set_timing_derate` factors scale cell delay values only. They do not scale slews or constraint tables. Late factors apply to late arrivals and early factors to early arrivals. Clock factors apply to the clock network, including a generated clock's source register. Data factors apply to every other arc.
5. **Checks.**
   - A setup check compares late data with the early capture clock. A hold check compares early data with the late capture clock.
   - Each constraint lookup uses the data slew of its own analysis as `constrained_pin_transition`, and the capture clock pin's slew from the same capture arrival as `related_pin_transition`.
   - Edge pairing works the same for any two clocks, including unrelated clocks and a master paired with its generated clock. The setup capture edge is the nearest capture edge strictly after the launch edge, minimised over every launch edge in the common period. The common period is the least common multiple of the two periods.
   - Periods need not be whole multiples of each other. Treat each period as an exact fraction when you find the least common multiple. For example, periods 0.4 and 0.7 ns have a common period of 2.8 ns.
   - Under exceptions, edges shift as SDC 2.1 defines by default. A multicycle setup moves the capture edge (`-end`), by whole capture periods. A multicycle hold moves the launch edge (`-start`), by whole launch periods. The default hold check follows the setup relationship.
   - The hold relationship is the setup relationship (which already includes any multicycle setup shift), minus the shorter of the launch and capture periods, minus the `-hold` multiplier times the launch period. The multiplier is 0 when there is no `-hold` exception. This also holds when the launch and capture clocks have different periods.
6. **Generated clocks.** A generated clock's waveform comes from its master, the clock at its `-source` pin, with period `P`, rising edge `r`, and falling edge `f`:
   - `-multiply_by k` gives period `P/k`, rising edge `r`, and falling edge `r + (f - r)/k`.
   - `-edges {e1 e2 e3}` counts the master's edges from its first rising edge. Edge `e` is at `r + ((e - 1) div 2) * P` when `e` is odd, and at `f + ((e - 1) div 2) * P` when `e` is even. The generated clock rises at edge `e1` and falls at edge `e2`, and its period is edge `e3` minus edge `e1`.
   - `-divide_by n` is the same as `-edges {1, n+1, 2n+1}`.
   - Every check, launch, and latch window that involves a generated clock uses the generated clock's own derived edges, never its master's. A latch enabled by a generated clock opens, closes, and launches Q at the generated clock's own edges.
   - A generated clock's `-source` may be a pin clocked by another generated clock. The waveform, the latency, and the clock-path tracing of rule 7 then apply step by step through each level. The clock path of such a clock passes through both source registers' clock-to-output arcs.
7. **Common path pessimism removal (CPPR).** On propagated clocks, setup and hold slack get a credit for the clock-network pins that the launch and capture clock paths share.
   - Path tracing. Every clock-network pin records, for each transition and separately for its late and its early arrival, the arc input pin and input transition that set that arrival. When several arcs give the same arrival, the smaller (pin name, transition) pair in string order wins, so `fall` comes before `rise` on the same pin. A generated clock's source pin records its register's clock pin at `rise`. A clock path is the chain of these records from a sequential clock pin back to its clock source port.
   - The launch path starts at the launching clock pin at `rise` and is traced in the launch analysis: late for setup, early for hold. The launching clock pin is the clock pin of the register or latch whose clock-to-output arc launched the data. For a latch Q arrival that came through D, it is that latch's enable pin. Data launched from an input port has no launch path and gets no credit. The capture path starts at the capturing clock pin and is traced in the capture analysis: early for setup, late for hold. It starts at `rise` for a register and for a latch setup, and at `fall` for a latch hold.
   - Credit. The last common pin is the pin on the launch path nearest the launching clock pin that the capture path also passes. The credit is that pin's late clock arrival minus its early clock arrival, for the transition the launch path has there. It is 0 when the capture path passes that pin with the opposite transition, when the paths share no pin, or when the clocks are ideal. Add the setup credit to setup slack and the hold credit to hold slack.
8. **Level-sensitive latches.**
   - A latch is transparent while its enable is high. Its opening edge is the clock edge whose propagation raises the enable pin. Its closing edge is the one that lowers it. Both follow the unateness of the clock network.
   - A path ends at the latch's D, and exceptions do not continue through the latch.
   - Setup and borrow. For each D arrival, `S` is the setup relationship from its launch edge to the opening edge, including the multicycle shift. The opening time is `S`, plus the enable's early clock latency at its opening transition, plus the setup CPPR credit. The open window `W` runs from the opening edge to the next closing edge of the latch's clock. The borrow limit is `W`, plus the early latency at the closing transition, minus the early latency at the opening transition, minus the setup constraint, and never below 0. Look up the setup constraint against the enable's closing transition, the edge `setup_falling` names. The borrow is the late D arrival minus the opening time, never below 0 and never above the borrow limit. Setup slack is the opening time plus the borrow minus the late D arrival.
   - Hold. Time a latch's hold check as for a register clocked at the closing edge.
   - Q launch. Q launches at the latch's own opening edge. Its enable launch is the enable's clock latency at its opening transition plus the enable-to-Q arc. Every D arrival whose borrow is above 0 also reaches Q, at that D arrival minus its `S`, plus the D-to-Q arc. That arc uses the D arrival's late slew and the late data factor. Q's late arrival and late slew are the largest of these. Its early arrival comes from the enable launch alone. So a Q arrival is measured from the opening edge.
   - Latches can form a chain: a Q arrival that came through D feeds the next latch's D like any other arrival, so borrowed time passes from latch to latch.
9. **Exceptions.** A `-through` list matches if the path passes any one of its pins. A false path removes its checks. An endpoint left with no check reports `null` for that check and does not count toward WNS or TNS.
10. **Path-based re-timing.** After the graph-based analysis, re-time the 5 endpoints with the smallest graph-based setup slack, chosen from register D pins and output ports. Latch D pins are not candidates. Ties go to the lexicographically smaller name, and when fewer than 5 have a setup check, take them all. For each one:
    - Trace one path back from the endpoint, at the transition and launch group of the check that sets its setup slack. If both transitions give the same slack, use `rise`. At each pin, step back through the input that set its late arrival, until you reach the start point: a register clock pin, an input port, or a latch Q. Keep the start point's graph-based late arrival and slew.
    - Along that path, evaluate every arc at the slew carried along the path itself, not the pin's worst graph slew. Apply the late data derate on data arcs; the late clock derate stays on the launch clock path.
    - On the capture side, work as in graph-based analysis, except that the constraint lookup uses the path's own data slew. The CPPR credit comes from the path's own launch and capture clock paths.
    - Report the result in `pba_setup`.

## Report

`R` is one JSON object with exactly these keys:

- `wns_setup`, `tns_setup`, `wns_hold`, `tns_hold`. WNS is the smallest endpoint slack, or `null` when no endpoint has that check. TNS is the sum of the negative endpoint slacks.
- `endpoints`: a map from every endpoint name to `{"setup": slack, "hold": slack}`. Endpoints are the D pins of sequential cells, named `inst/D`, and the output ports that have `set_output_delay`, named by the port. An endpoint's slack is the minimum over its checks.
- `arrivals`: a map from every pin outside the clock network that has an arrival to `{"late_rise", "late_fall", "early_rise", "early_fall"}`. The late values are the largest and the early values the smallest of the pin's arrivals, each measured from the edge that launched it, or `null`. Pins are named `inst/pin`, and ports by the port.
- `borrow`: a map from every latch D endpoint to its largest borrow, or `null` when it has no setup check.
- `pba_setup`: a map from each of the up to 5 re-timed endpoints of rule 10 to its path-based setup slack.

Every number is in ns.

**Exit status.** D1 exits 0 after writing `R`. It exits 2 without writing `R` when an input is malformed, refers to an undefined cell, pin, port, clock, or object, or uses a construct outside the subset above.

## Grading

Every number is checked to within `1e-6` ns. Keys must match exactly, and `null` must appear exactly where these rules leave a check absent. Hidden cases are drawn fresh for each run. A run that takes longer than 20 s is stopped, and every value of that case counts as wrong.

The reward is 0.9 times the weighted mean (`weighted-mean`) of the compiled checks of D1 on the hidden cases, plus 0.1 times the weighted mean of the judged reviews of D1's source. Each check and review scores pass or fail at its weight. So compiled checks make up 90% of the reward and judged reviews 10%. If D1 is missing, empty, or does not compile, the reward is 0.0. A run passes only when its reward is exactly 1.0.
