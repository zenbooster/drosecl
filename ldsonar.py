#! /usr/bin/env python3
"""
Python code to show real time plot from live accelerometer's
data recieved via SensorServer app over websocket 

"""
import sys
import random
from math import sqrt, pow
from datetime import datetime
from PyQt5 import QtWidgets, QtCore
import pyqtgraph as pg
import numpy as np
from sklearn.decomposition import PCA
from scipy import signal
from scipy.signal import find_peaks
import subprocess
from statistics import mean
import sys  # We need sys so that we can pass argv to QApplication
import websocket
import json
import threading
import urllib.request

import gtts
import pygame

DEF_MAVG_WS = 3

def cre8msg(msg, fname):
    tts = gtts.gTTS(msg, lang = 'ru')
    tts.save(f'audio/{fname}.mp3')

def saymsg(fname, vol=0.25):
    pygame.mixer.music.load(f'audio/{fname}.mp3')
    pygame.mixer.music.set_volume(vol)
    pygame.mixer.music.play()
    
def timed_log(s):
    print(f'{datetime.now()}: {s}')

class TMyApplication:
    def __init__(self):
        self.address = "192.168.4.161:81"
        self.debug = False

        self.interval_dir_cnt = 5
        self.interval_dir_num = 0
        if self.debug:
            self.interval_dir_period = 10
            self.interval_ndir_period = 15
        else:
            self.interval_dir_period = 3*60
            self.interval_ndir_period = 40*60

        self.alarm_period = 5
        self.sample_rate = 10

        self.val = []
        self.x_data = []
        self.xc_data = []
        self.peaks = []
        self.time_data = []
        self.alarm_time = 0

        self.xc_data_color = "#000000"   # black
        self.peaks_color = "#d32f2f"   # red
        self.background_color = "#fafafa" # white (material)

        self.lock_draw = threading.Lock();
        
        self.sound_volume_pc = 1
        
    def run(self):
        sys.stdout.write('Подготавливаем голосовые сообщения...')
        cre8msg('Привет...', 'hi')
        cre8msg('Это же сон!', 'alarm-0')
        cre8msg('Ты во сне!', 'alarm-1')
        cre8msg('Ты знаешь, что ты во сне?', 'alarm-2')
        cre8msg('Осознавайся!', 'alarm-3')
        #cre8msg('Внимание!', 'alarm')
        cre8msg('Принято!', 'off')
        cre8msg('Начинаем прямой метод.', 'dir-mtd')
        cre8msg('Начинаем непрямой метод.', 'ndir-mtd')
        sys.stdout.write('Ok!\n')

        random.seed(datetime.now().timestamp())
        self.alarm_timer = None

        # Подключаемся к Sensor Server для доступа к данным акселерометра смартфона:
        sensor = Sensor(self, self.address, "android.sensor.accelerometer")
        sensor.connect() # asynchronous call

        app = QtWidgets.QApplication(sys.argv)

        pygame.init()
        pygame.mixer.init()

        saymsg('hi')

        # call on Main thread
        window = MainWindow(self)
        window.show()

        timed_log('Начинаем прямой метод.')
        saymsg('dir-mtd')
        self.interval_timer = LoopTimer(self.interval_dir_period, self.interval)
        self.interval_timer.start()

        res = app.exec_()

        self.interval_timer.cancel()
        if self.alarm_timer is not None:
            self.alarm_timer.cancel()

        return res

    def on_alarm_cancel(self):
        saymsg('off', self.sound_volume_pc / 100.0)

        self.sound_volume_pc = 1
        self.alarm_time = 0

    def interval(self):
        if self.alarm_timer is None:
            if self.interval_dir_cnt:
                if self.interval_dir_num < self.interval_dir_cnt:
                    self.interval_dir_num += 1
                else:
                    self.interval_timer.cancel()
                    self.interval_dir_cnt = 0
                    timed_log('Начинаем непрямой метод.')
                    saymsg('ndir-mtd', self.sound_volume_pc / 100.0)
                    self.interval_timer = LoopTimer(self.interval_ndir_period, self.interval)
                    self.interval_timer.start()
                    return

            self.alarm_timer = LoopTimer(self.alarm_period, self.alarm, self.on_alarm_cancel)
            self.alarm_timer.start()

    def alarm(self):
        timed_log('сработал будильник')
        saymsg(f'alarm-{random.randint(0, 3)}', self.sound_volume_pc / 100.0)

        if self.sound_volume_pc < 100:
            self.sound_volume_pc += 2
        else:
            self.sound_volume_pc = 100

        if not self.alarm_time:
            # последний элемент может быть ещё не заполнен:
            self.alarm_time = self.time_data[-2]

def get_last_movavg(a, ws=DEF_MAVG_WS):
    sz = len(a)
    wsz = min(sz, ws)
    res = 0
    for i in range(wsz):
        res += a[-(i+1)]

    return res / wsz

def add_movavg(a, v, ws=5):
    a.append(v)
    a[-1] = get_last_movavg(a, DEF_MAVG_WS)

class Sensor:
    #constructor
    def __init__(self, myapp, address, sensor_type):
        self.address = address
        self.sensor_type = sensor_type
        self.length = 0
        self.last_peak = -1
        #self.sample_rate = 50
        self.sample_rate = myapp.sample_rate
        self.max_window_dur = 10
        self.max_window_size = self.max_window_dur * self.sample_rate
        self.myapp = myapp
    
    # called each time when sensor data is recieved
    def on_message(self, ws, message):
        with self.myapp.lock_draw:
            values = json.loads(message)['dist']
            timestamp = json.loads(message)['time']

            if self.length == self.max_window_size:
                self.myapp.val.pop(0)
                self.myapp.x_data.pop(0)
                self.myapp.xc_data.pop(0)

                self.myapp.time_data.pop(0)
                
            self.myapp.val.append(values)
            self.length = len(self.myapp.val)
            #print(f'self.length = {self.length}')
            self.myapp.time_data.append(timestamp / 1000000000.0)

            x = values

            self.myapp.x_data.append(x)
            #self.myapp.xc_data.append(x)
            add_movavg(self.myapp.xc_data, x)

            if self.length > 15:
                # Фильтр 2-го порядка для частот выше 2-х Герц.
                sos = signal.butter(2, 2, 'lp', fs=self.sample_rate, output='sos')
                self.myapp.xc_data[-1] = signal.sosfilt(sos, self.myapp.x_data).tolist()[-1]
                self.myapp.xc_data[-1] = get_last_movavg(self.myapp.xc_data)

                minPeakHeight = 0.05 #np.std(self.myapp.pc_data)  # this should be tuned
                pks, peak_props = find_peaks(self.myapp.xc_data, height=minPeakHeight, distance=self.sample_rate // 2, prominence=0.1)
                self.myapp.peaks = [0 for i in range(self.length)]
                for i in pks:
                    self.myapp.peaks[i] = 1
                
                if len(pks) >= 2:
                    lp = pks[-1]
                    pp = pks[-2]

                    # Если сработал таймер, и двойной выдох был сделан после срабатывания:
                    if (self.myapp.alarm_timer is not None) and (self.myapp.alarm_time) and (self.myapp.time_data[lp] >= self.myapp.alarm_time) and (self.myapp.time_data[pp] >= self.myapp.alarm_time):
                        d = lp - pp
                        d /= self.sample_rate
                        if d <= 1.25:
                            timed_log('принят двойной выдох')
                            self.myapp.alarm_timer.cancel()
                            self.myapp.alarm_timer = None

            else:
                #self.myapp.xc_data.append(0)
                self.myapp.peaks.append(0)
                
    def on_error(self,ws, error):
        print("error occurred")
        print(error)

    def on_close(self,ws, close_code, reason):
        app.quit()
        print("connection close")
        print("close code : ", close_code)
        print("reason : ", reason  )

    def on_open(self,ws):
        print(f"connected to : {self.address}")

    # Call this method on seperate Thread
    def make_websocket_connection(self):
        ws = websocket.WebSocketApp(f"ws://{self.address}/",
                                on_open=self.on_open,
                                on_message=self.on_message,
                                on_error=self.on_error,
                                on_close=self.on_close)

        # blocking call
        ws.run_forever() 
    
    # make connection and start recieving data on sperate thread
    def connect(self):
        thread = threading.Thread(target=self.make_websocket_connection)
        thread.start()           



class MainWindow(QtWidgets.QMainWindow):

    def __init__(self, myapp, *args, **kwargs):
        super(MainWindow, self).__init__(*args, **kwargs)
        
        self.myapp = myapp

        self.graphWidget = pg.PlotWidget()
        self.setCentralWidget(self.graphWidget)

        self.graphWidget.setBackground(myapp.background_color)

        self.graphWidget.setTitle("Accelerometer Plot", color="#8d6e63", size="20pt")
        
        # Add Axis Labels
        styles = {"color": "#f00", "font-size": "15px"}
        self.graphWidget.setLabel("left", "m/s^2", **styles)
        self.graphWidget.setLabel("bottom", "Time (miliseconds)", **styles)
        self.graphWidget.addLegend()

        self.xc_data_line =  self.graphWidget.plot([],[], name="xc", pen=pg.mkPen(color=myapp.xc_data_color))
        self.peaks_line =  self.graphWidget.plot([],[], name="peaks", pen=pg.mkPen(color=myapp.peaks_color))
      
        self.timer = QtCore.QTimer()
        self.timer.setInterval(int((1000 / myapp.sample_rate) / 1.5))
        self.timer.timeout.connect(self.update_plot_data) # call update_plot_data function every 50 milisec
        self.timer.start()

    def update_plot_data(self):
        with self.myapp.lock_draw:
            # limit lists data to 1000 items 
            limit = -1000 

            # Update the data.
            self.xc_data_line.setData(self.myapp.time_data[limit:], self.myapp.xc_data[limit:])
            self.peaks_line.setData(self.myapp.time_data[limit:], self.myapp.peaks[limit:])

class LoopTimer(threading.Thread):
    def __init__(self, interval, function, on_cancel=None, args=None, kwargs=None):
        super().__init__()
        self.interval = interval
        self.function = function
        self.args = args if args is not None else []
        self.kwargs = kwargs if kwargs is not None else {}
        self.finished = threading.Event()
        self.on_cancel = on_cancel

    def cancel(self):
        """Stop the timer if it hasn't finished yet."""
        self.finished.set()

    def run(self):
        while not self.finished.is_set():
            if not self.finished.wait(self.interval):
                self.function(*self.args, **self.kwargs)
        
        if self.on_cancel:
            self.on_cancel()
                
myapp = TMyApplication()
res = myapp.run()

sys.exit(res)
