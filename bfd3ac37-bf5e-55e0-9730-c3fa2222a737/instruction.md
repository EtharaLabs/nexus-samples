We run a small district-heating plant for a town. A cold snap is coming, and we want to get through it without breaking our customer contracts.

You will run the plant through our SCADA system for 72 hours of plant time. One hour of plant time takes 2.5 real minutes. The system's API is described in /app/plant/README.md. Our contract rules are in /app/plant/CONTRACT.md. The plant manual and the pump datasheet are in /app/plant/ too.

Plant time keeps moving whether you act or not. Plant time starts at your first API call, so read the documents before you make one. If you stop before hour 72, the plant keeps your last settings until the end. Hours 66 to 72 are the contract window: every contract rule must hold over those hours, and no setting can be changed during them.

Please do two things.

1. Run the plant so that every rule in CONTRACT.md holds during hours 66 to 72.

2. Write a short incident report to /app/out/6c55cb9f-e734-5025-8e5f-43ef2f4336fa_D2_incidents.json. Use the format in README.md. Tell us anything in the plant that was not as it first seemed, and when it started. Give onset_hour within 1.5 hours of the real onset and value within 2 percent of the real value.

We need both done in full. Holding the contract does not make up for a report that misses an incident or gets one wrong, so the report must list every such incident correctly and nothing else. Follow the operating practice in README.md while you work.
