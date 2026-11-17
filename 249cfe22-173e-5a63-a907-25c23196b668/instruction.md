This island runs on its own small grid: two diesel generators, a solar farm, a battery, and loads we can switch off in groups, plus a link to the mainland utility. The utility has scheduled an outage of that link near the end of the next three days, and the island has to ride through it.

Operate the microgrid for 72 hours of grid time with the dispatch API. Five real minutes make one grid hour, and grid time begins when you send your first API request, so read the documents before you send one. Read /app/plant/README.md for the API and /app/plant/CONTRACT.md for our supply obligations. The grid manual and the generator datasheet are in /app/plant/ as well.

Grid time does not pause. If you stop sending requests, the grid keeps your most recent accepted settings to the end of hour 72. Hours 66 to 72 are the contract window, and no dispatch change is taken in that span.

Your two tasks:

(a) Dispatch the grid so that all of CONTRACT.md is honoured over hours 66 to 72.

(b) File an incident report as /app/out/249cfe22-173e-5a63-a907-25c23196b668_D2_incidents.json in the README.md format. Report every part of the grid that behaved differently from how it first appeared, and the hour it started. Reported numbers need to be close: onset_hour within 1.5 hours of the real onset, and value within 2 percent of the real value.

Both tasks have to be done in full. Honouring the contract does not make up for a report with a missed or a wrong entry, so the report must list every such incident correctly and nothing else. Follow the operating practice in README.md while you work.
