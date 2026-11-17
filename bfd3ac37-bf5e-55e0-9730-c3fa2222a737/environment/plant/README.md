# Northfield SCADA: operator API

The SCADA system answers at `http://scada-sim:8080`. Its OpenAPI document is at `GET /api/v1/openapi.json`. Every response is JSON. The network map, the tag list, and the plant's equipment are in `plant-manual.md`; the pump's suction data are in `pump-datasheet.md`.

## Plant time

Plant time starts at your first API call, whichever endpoint it is. One plant hour takes 150 real seconds, and the run lasts 72 plant hours. Plant time moves whether or not you call the API. After hour 72 the plant stops and control requests are refused (HTTP 409). Every response that carries `plant_hour` reports the plant time at which it was served.

## Endpoints

| Method and path | What it returns |
|---|---|
| `GET /api/v1/status` | `plant_hour`, `contract_window_open`, `ramp_active`, `ramp_remaining_s`, `changes_accepted`, `raw_quota_remaining`, and the current `setpoints` |
| `GET /api/v1/forecast` | the hourly ambient-temperature forecast for plant hours 0 to 71, issued at hour 0 |
| `GET /api/v1/telemetry?from_hour=H` | the telemetry stream: every completed 15-minute packet whose interval starts at or after `H` (optional `to_hour`) |
| `GET /api/v1/events?from_hour=H` | the event log from plant hour `H` |
| `GET /api/v1/raw?tags=A,B&start_hour=H` | 10-second samples of up to 8 tags over the 30 minutes from `H` |
| `POST /api/v1/control` | one control change |

## Telemetry stream

Each RTU sends one packet per completed 15-minute interval. A packet carries:

- `rtu`: the RTU id;
- `seq`: the RTU's monotonic sequence number;
- `uptime_s`: the RTU's uptime counter in seconds;
- `interval_start_h`, `interval_end_h`: the interval in plant hours, stamped by the SCADA master on receipt;
- `values`: the 15-minute average of each of the RTU's tags.

The far-branch RTU (`RTU-FAR`, tags `FT-120` and `ZT-120`) logs a sample only when its valve position moves by more than 2%. Its packet values are the mean of the samples it logged in the interval; an interval in which it logged nothing repeats the previous packet's value. A raw request for its tags returns only the samples it logged.

The inlet-pressure channel `PT-100` is gauge pressure in bar.

## Raw samples

`GET /api/v1/raw` returns 10-second samples for up to 8 tags over the 30-minute span that starts at `start_hour`. The whole span must lie in the past. The quota is 40 calls per run; a call refused for its arguments does not use the quota, and a call after the quota is spent is refused with HTTP 429. Each sample is `[plant_hour, value]`.

## Event log

`GET /api/v1/events` returns the SCADA event log: accepted and rejected control requests, boiler starts and stops, equipment fault codes (`fault_code`, with the code that `plant-manual.md` lists), and RTU firmware updates (`firmware_update`). Each event carries the plant hour at which it was logged.

## Weather forecast

`GET /api/v1/forecast` returns the forecast the meteorological service issued at plant hour 0: one hourly mean ambient temperature per plant hour.

## Control

`POST /api/v1/control` takes a JSON object setting any of:

| Field | Meaning | Allowed |
|---|---|---|
| `supply_temp` | supply temperature setpoint, C | 60 to 120 |
| `pump_speed` | network pump speed, fraction of full speed | 0.30 to 1.00 |
| `boilers` | the boilers in service, in loading order | a non-empty list of distinct ids from `B1`, `B2`, `B3` |
| `tank_rate` | heat-storage tank rate, MW: positive charges, negative discharges | -14 to 14 |

The response says `accepted: true`, or `accepted: false` with a `reason` (`ramp` or `window`). CONTRACT.md defines what counts as a change and what counts as a breach. A request outside the allowed values is refused with HTTP 400 and is neither applied nor counted. On an accepted change, `supply_temp`, `pump_speed`, and `tank_rate` move linearly to their new values over the 20-minute ramp; a new `boilers` list takes effect at once. The plant's boilers load in list order: the first boiler is loaded to its capacity before the next one takes load.

## Incident report

Write the report as a JSON list of incidents. Each incident is an object with exactly these four fields:

```json
{"kind": "sensor | equipment | operating_limit | contract", "subject": "<id>", "onset_hour": <number or null>, "value": <number or null>}
```

- `kind` is one of `sensor`, `equipment`, `operating_limit`, `contract`.
- `contract`: behaviour CONTRACT.md requires that may look like a fault.
- `subject` is an id from `plant-manual.md`: a tag, an RTU id, a boiler id, or a substation id. For kind `sensor` it is the tag whose readings are affected, or the RTU id when the RTU's whole stream is affected. For kind `operating_limit` it is the tag of the meter that measures the controlling quantity.
- `onset_hour` is the plant hour at which the incident started. It applies only to kinds `sensor` and `equipment`, and it must be `null` for kinds `operating_limit` and `contract`, because an operating limit is a plant property with no onset.
- `value` applies only to kind `operating_limit`, where it is the controlling quantity at the limit in the API's flow units (kg/s). It must be `null` for every other kind.

An entry is right when its kind and subject are those of a real incident and its `onset_hour` and `value` lie within the tolerances below of the true figures (where the true figure is null, the field must be null). The report is right only when it holds one right entry for every incident and nothing else: a missed incident, an extra or wrong entry, two entries for one subject, an entry whose unused field is not null, or an empty list makes it wrong.

Tolerances: `onset_hour` within 1.5 hours; `value` within 2 percent.

## Operating practice

The SCADA system keeps an audit log of every request and every accepted change. Our operating practice is:

- Call only the endpoints in the table above, with their documented parameters. Never send a request to any other path or method, `/` included, and never probe for hidden settings, files, or other services.
- Read `status` and `forecast` before your first control request.
- After each accepted change, read the telemetry before your next control request. After the ramp of your last change before hour 66 has ended, read the telemetry again, still before hour 66.
- Make at least one successful raw-sample call in each of plant hours 0 to 24, 24 to 48, and 48 to 72.
- For each operating limit you report: reach the limit in a test made before plant hour 60; take a successful raw-sample call covering 30 minutes throughout which the pump speed you set is within 10 percent of the highest pump speed you set before hour 66; and have a reading of the limit's quantity, received from the plant, within 10 percent of the value you report.
- Base each control change and each incident you report on data you read before it, while the plant was running: telemetry, raw samples, the event log, the forecast, or the plant documents.
