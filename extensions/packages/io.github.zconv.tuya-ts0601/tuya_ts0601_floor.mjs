import * as exposes from "zigbee-herdsman-converters/lib/exposes";
import * as tuya from "zigbee-herdsman-converters/lib/tuya";

const e = exposes.presets;
const ea = exposes.access;

export default {
    fingerprint: tuya.fingerprint("TS0601", ["_TZE204_zconvfl1"]),
    model: "TS0601_floor_zconv",
    vendor: "Tuya",
    description: "Floor heating thermostat",
    fromZigbee: [tuya.fz.datapoints],
    toZigbee: [tuya.tz.datapoints],
    onEvent: tuya.onEventSetTime,
    configure: tuya.configureMagicPacket,
    exposes: [
        e.climate()
            .withSetpoint("current_heating_setpoint", 5, 35, 0.5, ea.STATE_SET)
            .withLocalTemperature(ea.STATE)
            .withSystemMode(["off", "heat"], ea.STATE_SET)
            .withRunningState(["idle", "heat"], ea.STATE),
        e.child_lock(),
    ],
    meta: {
        tuyaDatapoints: [
            [1, "system_mode", tuya.valueConverterBasic.lookup({off: false, heat: true})],
            [2, "current_heating_setpoint", tuya.valueConverter.divideBy10],
            [3, "local_temperature", tuya.valueConverter.divideBy10],
            [36, "running_state", tuya.valueConverterBasic.lookup({heat: 0, idle: 1})],
            [40, "child_lock", tuya.valueConverter.lockUnlock],
        ],
    },
};
