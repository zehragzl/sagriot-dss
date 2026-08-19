import time
from datetime import datetime
from zoneinfo import ZoneInfo

import serial
import board
import adafruit_sht31d
import adafruit_scd4x
import adafruit_dps310
import adafruit_tsl2591
import adafruit_ds3231

from .config import (
    TZ_NAME, SOIL_PORT, SOIL_BAUDRATE, SOIL_SLAVE_ID,
    VWC_FIELD_CAPACITY, LUX_TO_PAR,
)

EC_US_TO_DS = 0.001


def modbus_crc(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


class SensorHub:
    def __init__(self):
        self.available = {}
        self.tz = ZoneInfo(TZ_NAME)        
        i2c = board.I2C()
        self.sht31 = self._init("sht31d", lambda: adafruit_sht31d.SHT31D(i2c))
        self.scd41 = self._init("scd41", lambda: self._start_scd(i2c))
        self.dps310 = self._init("dps310", lambda: adafruit_dps310.DPS310(i2c))
        self.tsl2591 = self._init("tsl2591", lambda: adafruit_tsl2591.TSL2591(i2c))
        self.rtc = self._init("ds3231", lambda: adafruit_ds3231.DS3231(i2c))
        if VWC_FIELD_CAPACITY is None:
            print("[sensors] VWC_FIELD_CAPACITY not calibrated - soil_fc will not be reported")

    def _init(self, name, factory):
        try:
            device = factory()
            self.available[name] = True
            return device
        except Exception as error:
            self.available[name] = False
            print(f"[sensors] {name} unavailable: {error}")
            return None

    def _start_scd(self, i2c):
        sensor = adafruit_scd4x.SCD4X(i2c)
        sensor.start_periodic_measurement()
        return sensor

    def timestamp(self):
        if self.rtc is not None:
            try:
                t = self.rtc.datetime
                return datetime(t.tm_year, t.tm_mon, t.tm_mday,
                                t.tm_hour, t.tm_min, t.tm_sec, tzinfo=self.tz)
            except Exception as error:
                print(f"[sensors] RTC read failed: {error}")
        return datetime.now(self.tz)

    def read_soil(self, attempts=3):
        for attempt in range(attempts):
            result = self._read_soil_once()
            if result is not None:
                return result
            time.sleep(0.3)
        return None

    def _read_soil_once(self):
        request = bytes([SOIL_SLAVE_ID, 0x04, 0x00, 0x00, 0x00, 0x03])
        request += modbus_crc(request)

        try:
            with serial.Serial(
                SOIL_PORT,
                SOIL_BAUDRATE,
                bytesize=8,
                parity=serial.PARITY_NONE,
                stopbits=1,
                timeout=2
            ) as ser:
                ser.reset_input_buffer()
                ser.write(request)
                ser.flush()

                response = bytearray()

                deadline = time.time() + 5

                while len(response) < 11 and time.time() < deadline:
                    chunk = ser.read(11 - len(response))
                    if chunk:
                        response.extend(chunk)

        except Exception as error:
            print(f"[sensors] soil sensor error: {error}")
            return None

        response = bytes(response)

        if len(response) < 11:
            print(f"[sensors] soil sensor: response too short ({len(response)}/11)")
            return None

        if response[0] != SOIL_SLAVE_ID or response[1] != 0x04 or response[2] != 6:
            print("[sensors] soil sensor: unexpected frame")
            return None

        if modbus_crc(response[:9]) != response[9:11]:
            print(
                f"[sensors] soil sensor: CRC mismatch "
                f"(got {response[9:11].hex()}, "
                f"expected {modbus_crc(response[:9]).hex()})"
            )
            return None

        vwc = int.from_bytes(
            response[3:5], "big", signed=True
        ) / 10

        temperature = int.from_bytes(
            response[5:7], "big", signed=False
        ) / 10

        ec_us = int.from_bytes(
            response[7:9], "big", signed=False
        )

        return temperature, vwc, ec_us

    def read(self):
        row = {}
        if self.sht31 is not None:
            try:
                row["air_temp"] = round(self.sht31.temperature, 2)
                row["air_humidity"] = round(self.sht31.relative_humidity, 2)
            except Exception as error:
                print(f"[sensors] SHT31D read failed: {error}")
        if self.scd41 is not None:
            try:
                if self.scd41.data_ready:
                    row["co2"] = float(self.scd41.CO2)
            except Exception as error:
                print(f"[sensors] SCD41 read failed: {error}")
        if self.dps310 is not None:
            try:
                row["pressure"] = round(self.dps310.pressure, 2)
            except Exception as error:
                print(f"[sensors] DPS310 read failed: {error}")
        if self.tsl2591 is not None:
            try:
                row["lux"] = round(self.tsl2591.lux, 2)
                row["par"] = round(row["lux"] * LUX_TO_PAR, 2)
            except Exception as error:
                print(f"[sensors] TSL2591 read failed: {error}")
        soil = self.read_soil()
        if soil is not None:
            soil_temp, vwc, ec_us = soil
            row["soil_temp"] = soil_temp
            row["soil_vwc"] = vwc
            row["ec"] = round(ec_us * EC_US_TO_DS, 3)
            if VWC_FIELD_CAPACITY:
                row["soil_fc"] = round(vwc / VWC_FIELD_CAPACITY * 100, 1)
        return self.timestamp(), row


if __name__ == "__main__":
    hub = SensorHub()
    print(hub.available)
    timestamp, row = hub.read()
    print(timestamp)
    for channel, value in sorted(row.items()):
        print(f"  {channel:14s} {value}")