"""The OpenAPI document the sidecar serves at /api/v1/openapi.json. Every response field is listed."""

_num = {"type": "number"}
_str = {"type": "string"}
_int = {"type": "integer"}
_bool = {"type": "boolean"}
_err = {
    "description": "client error",
    "content": {
        "application/json": {
            "schema": {"type": "object", "properties": {"error": _str}}
        }
    },
}


def _ok(schema: dict) -> dict:
    return {
        "200": {
            "description": "ok",
            "content": {"application/json": {"schema": schema}},
        }
    }


_setpoints = {
    "type": "object",
    "properties": {
        "supply_temp": _num,
        "pump_speed": _num,
        "boilers": {"type": "array", "items": _str},
        "tank_rate": _num,
    },
}
_packet = {
    "type": "object",
    "properties": {
        "rtu": _str,
        "seq": _int,
        "uptime_s": _int,
        "interval_start_h": _num,
        "interval_end_h": _num,
        "values": {
            "type": "object",
            "additionalProperties": {"type": "number", "nullable": True},
        },
    },
}
_event = {
    "type": "object",
    "properties": {
        "hour": _num,
        "source": _str,
        "event": _str,
        "subject": _str,
        "code": _str,
        "version": _str,
        "reason": _str,
        "change": {"type": "object"},
    },
}

SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Northfield district heating SCADA", "version": "4.2"},
    "servers": [{"url": "http://scada-sim:8080"}],
    "paths": {
        "/api/v1/status": {
            "get": {
                "summary": "Plant clock, ramp state, change count, raw quota, setpoints",
                "responses": _ok(
                    {
                        "type": "object",
                        "properties": {
                            "plant_hour": _num,
                            "contract_window_open": _bool,
                            "ramp_active": _bool,
                            "ramp_remaining_s": _int,
                            "changes_accepted": _int,
                            "raw_quota_remaining": _int,
                            "setpoints": _setpoints,
                        },
                    }
                ),
            }
        },
        "/api/v1/forecast": {
            "get": {
                "summary": "Hourly ambient forecast for plant hours 0 to 71, issued at hour 0",
                "responses": _ok(
                    {
                        "type": "object",
                        "properties": {
                            "issued_hour": _int,
                            "hourly_ambient_c": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {"hour": _int, "ambient_c": _num},
                                },
                            },
                        },
                    }
                ),
            }
        },
        "/api/v1/telemetry": {
            "get": {
                "summary": "15-minute telemetry packets, one per RTU per completed interval",
                "parameters": [
                    {"name": "from_hour", "in": "query", "schema": _num},
                    {"name": "to_hour", "in": "query", "schema": _num},
                ],
                "responses": {
                    **_ok(
                        {
                            "type": "object",
                            "properties": {
                                "plant_hour": _num,
                                "packets": {"type": "array", "items": _packet},
                            },
                        }
                    ),
                    "400": _err,
                },
            }
        },
        "/api/v1/events": {
            "get": {
                "summary": "The SCADA event log",
                "parameters": [{"name": "from_hour", "in": "query", "schema": _num}],
                "responses": {
                    **_ok(
                        {
                            "type": "object",
                            "properties": {
                                "plant_hour": _num,
                                "events": {"type": "array", "items": _event},
                            },
                        }
                    ),
                    "400": _err,
                },
            }
        },
        "/api/v1/raw": {
            "get": {
                "summary": "10-second samples of up to 8 tags over one past 30-minute span (quota 40 per run)",
                "parameters": [
                    {
                        "name": "tags",
                        "in": "query",
                        "required": True,
                        "schema": _str,
                        "description": "comma-separated tags",
                    },
                    {
                        "name": "start_hour",
                        "in": "query",
                        "required": True,
                        "schema": _num,
                    },
                ],
                "responses": {
                    **_ok(
                        {
                            "type": "object",
                            "properties": {
                                "start_hour": _num,
                                "raw_quota_remaining": _int,
                                "samples": {
                                    "type": "object",
                                    "additionalProperties": {
                                        "type": "array",
                                        "items": {
                                            "type": "array",
                                            "items": _num,
                                            "description": "[plant hour, value]",
                                        },
                                    },
                                },
                            },
                        }
                    ),
                    "400": _err,
                    "429": _err,
                },
            }
        },
        "/api/v1/control": {
            "post": {
                "summary": "One control change: any of supply_temp, pump_speed, boilers, tank_rate",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": _setpoints}},
                },
                "responses": {
                    **_ok(
                        {
                            "type": "object",
                            "properties": {
                                "accepted": _bool,
                                "reason": _str,
                                "plant_hour": _num,
                            },
                        }
                    ),
                    "400": _err,
                    "409": _err,
                },
            }
        },
        "/api/v1/openapi.json": {
            "get": {"summary": "This document", "responses": _ok({"type": "object"})}
        },
    },
}
