#!/usr/bin/python
#
# Radio signal decoder
# for BRESSER WEATHER CENTER 5-IN-1
#
# Copyright (C) 2016 Andrea Fabrizi <andrea.fabrizi@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#
# rtl_fm command to use:
#   rtl_fm -M am -f 868.300M -s 48k -g 49.6 | ./test.py
#
import sys
import struct
import math
import time
import sqlite3
import signal
import os

class StdinNoMoreData(Exception):
    pass

class packet():

    def __init__(self, raw_data, debug = False):
        self.raw_data = raw_data
        self.humidity = 0
        self.temperature = 0.0
        self.wind_speed = 0.0
        self.rain = 0.0
        self.wind_direction = 0
        self.debug = debug
        self.station_id = 0

    def parse(self):

        #Converting raw data to a binary stream
        self.stream = ""
        digits = [self.raw_data[i:i+4] for i in range(0, len(self.raw_data), 4)]
        for digit in digits:
            n = int(digit, 2)
            self.stream+=chr(n)

        self.size = len(self.stream)

        if self.size != 66:
            return 1

        #Preamble
        preamble = self.stream[0:10]
        if preamble != "\x0A\x0A\x0A\x0A\x0A\x0A\x0A\x0A\x0A\x0A":
            return 2

        #Station ID
        self.station_id = struct.unpack(">i", self.stream[10:14])[0]

        #Checksum data
        for n in range(0,26):
            if ord(self.stream[14+n:15+n]) ^ 0xf != ord(self.stream[40+n:41+n]):
                return 4

        #Wind direction
        self.wind_direction = ord(self.stream[48:49])
        if self.wind_direction < 0 or self.wind_direction > 0xF:
            return 5

        #Wind
        wind_digit_1 = ord(self.stream[49:50])
        wind_digit_2 = ord(self.stream[50:51])
        wind_decimal = ord(self.stream[51:52])

        self.wind_speed = wind_digit_1 * 10 + wind_digit_2 + (float(wind_decimal)/10)

        #Temperature
        temp_digit_2 = ord(self.stream[54:55])
        temp_decimal = ord(self.stream[55:56])
        temp_sign = ord(self.stream[65:66])
        temp_digit_1 = ord(self.stream[57:58])

        self.temperature  = temp_digit_1 * 10 + temp_digit_2 + (float(temp_decimal)/10)

        if temp_sign != 0:
            self.temperature  = 0 - self.temperature

        #Humidity
        hum_digit_1 = ord(self.stream[58:59])
        hum_digit_2 = ord(self.stream[59:60])

        self.humidity = hum_digit_1 * 10 + hum_digit_2

        #Rain
        rain_digit_2 = ord(self.stream[60:61])
        rain_decimal = ord(self.stream[61:62])
        rain_digit_1 = ord(self.stream[63:64])

        self.rain = rain_digit_1 * 10 + rain_digit_2 + (float(rain_decimal)/10)

        return 0

    def printReadings(self):
        print time.strftime("%Y-%m-%d %H:%M:%S: "),
        print "Humidity: %d%% " % self.humidity,
        print "Temperature: %.1f" % self.temperature + u"\u00b0C ",
        print "Wind: %.1f m/s %s" % (self.getWindSpeed(), self.getWindDirection()),
        print "Rain: %.1f mm" % self.getRain(),
        print ""

    def packetInfo(self):
        print ""
        print "Packet size: %d" % self.size
        print "Hex data: ",
        print " ".join("{:02x}".format(ord(c)) for c in self.stream)
        print "Station ID: 0x%x" % self.getStationID()

    def store(self, dest):

        hexdata = " ".join("{:02x}".format(ord(c)) for c in self.stream)

        try:
            f = open(dest, "a")
            f.write("%s | %s | %d%% %.1fC %.1fm/s %s %.1fmm\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), hexdata, self.humidity, self.temperature,  self.getWindSpeed(), self.getWindDirection(),self.getRain()))
            f.close()
        except Exception as e:
            print "Error storing sample to file: %s" % e

    def getHumidity(self):
        return self.humidity

    def getTemperature(self):
        return self.temperature

    def getIntTemperature(self):
        return int(round(self.temperature * 10))

    def getWindSpeed(self):
        return self.wind_speed

    def getWindSpeedKm(self):
        return self.wind_speed * 3.6

    def getIntWindSpeed(self):
        return int(round(self.wind_speed * 10))

    def getIntWindSpeedKm(self):
        return int(round(self.getIntWindSpeed() * 10))

    def getWindDirection(self):
        directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        return directions[self.wind_direction]

    def getIntWindDirection(self):
        return self.wind_direction

    def getRain(self):
        return self.rain

    def getIntRain(self):
        return int(round(self.rain * 10))

    def getStationID(self):
        return self.station_id

class Bresser():

    def __init__(self, dumpfile = None, debug = False, printdata = False, noise = 0, station_id = 0):
        self.dumpfile = dumpfile
        self.printdata = printdata
        self.callback_func = None
        self.debug = debug
        self.noise = noise
        self.station_id = station_id

    def set_callback(self, callback_func):
        self.callback_func = callback_func

    def process_packet(self, raw_data):

        p = packet(raw_data, self.debug)

        if p.parse() == 0:
            if self.debug:
                p.packetInfo()

            if self.station_id > 0:
                if self.station_id != p.getStationID():
                    if self.debug:
                        print "Not matching station ID (0x%x)" % p.getStationID()
                    return

            if self.printdata:
                p.printReadings()

            if self.dumpfile:
                p.store(self.dumpfile)

            if self.callback_func:
                self.callback_func(p)

        elif self.debug:
            print "Invalid packed received"
            p.packetInfo()

    def get_sample_stdin(self):
        short = sys.stdin.read(2)
        if not short:
            raise StdinNoMoreData

        return abs(struct.unpack("h", short)[0])

    def process_signal(self, samples):

        buffer = ""

        #Normalising the samples
        for index, sample in enumerate(samples):
            if samples[index] > 0:
                #print "%d -> 1" % samples[index]
                samples[index] = 1
            else:
                #print "%d -> 0" % samples[index]
                samples[index] = 0

        prev_sample = 0
        count_prev_samples = 0

        #Reducing the samples
        for sample in samples:
            if sample == prev_sample:
                count_prev_samples += 1
                continue

            #6 is the rate for a 48Khz sampling
            rate = math.ceil(float(count_prev_samples) / 6)
            buffer+=str(prev_sample) * int(rate)

            prev_sample = sample
            count_prev_samples = 0

        #Stripping zeros from the signal
        buffer = buffer.strip("0")

        #If the buffer size is < 256 and > 252, probably the original packet
        #ends with 0s which has been stripped, so let's compensate
        if len(buffer) > 252 and len(buffer) < 264:
            buffer += "0" * (264 - len(buffer))

        self.process_packet(buffer)

    #Detecting sequences of data separated by silence
    def process_radio_data(self):

        samples = list()
        prev_sample = 0

        while True:

            count_prev_samples = 0

            #Reading silence
            sample = self.get_sample_stdin()
            while (sample <= self.noise):
                sample = self.get_sample_stdin()

            #Reading all data until there's silence for at least 300 samples (300 is good for a 48Khz sampling)
            while True:
                samples.append(sample)
                sample = self.get_sample_stdin()

                if sample <= self.noise:
                    sample = 0

                if sample == 0 and prev_sample == 0 and count_prev_samples > 300:
                    break

                if sample == prev_sample:
                    count_prev_samples += 1
                else:
                    count_prev_samples = 0

                prev_sample = sample

            self.process_signal(samples)
            samples = []
