""" Скрипт для параноиков/мошенников в общественных местах.
    Что делает?
        Счётчик, по достижению предела которого вызывается блокировка сеанса. Начинает отчёт, если открыто
        какое-либо приложение с каким-либо заголовком (используется regex), из какой-либо группы (напр. Gnome-terminal)
        либо любое другое XID окно (напр. открыли инкогнито в новом окне, добавляем его XID в список).

    Copyright 2017 John Ashley
    vk.com/ashftw
    v0.2-unstable
"""

import signal
import copy
import threading

import subprocess
import time
import sys
import re
import math

from PyQt5.QtCore import pyqtSlot, pyqtSignal, QThread, QObject, QCoreApplication, Qt
from PyQt5.QtGui import *
from PyQt5.QtWidgets import QSystemTrayIcon, QWidget, QApplication, QMenu


import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Wnck', '3.0')
# Docs: https://developer.gnome.org/libwnck/stable/WnckWindow.html
from gi.repository import Gtk as gtk
from gi.repository import Gdk as gdk
from gi.repository import GObject as gobject
from gi.repository import Wnck as wnck

signal.signal(signal.SIGINT, signal.SIG_DFL)

QCoreApplication.setAttribute(Qt.AA_X11InitThreads)


from PIL import Image
from PIL import ImageFont
from PIL import ImageDraw
from PIL.ImageQt import ImageQt


delay = 0.1
lock_after = (0*60+20)
# incubation_period = 0
incubation_period = (0*60+40)  # когда начать счётчик lock_after
is_autominimize = True

target_name = ['ImageMagic', 'Gimp', '.*mage,.*pixels\).*Mozilla Firefox', '.*History.*Chromium']
target_group = ['Gnome-terminal', 'Gnome-screenshot', 'TelegramDesktop', 'Eog', 'Shotwell', 'Tor Browser']
target_xid = []

# todo:
#  - word detection in 'Gnome-terminal'
#  - detect <ctrl+alt+[f1-f6]>
#  + add window to Target_app, eg Chomium-browser with social network tab
#  - do not launch without root!!!
# FIXME: счётчик не капает, если открыто два окна в хроме и в панеле выбрать какое именно окно открыть (мб добавить окну параметр?)

screen = wnck.Screen.get_default()

DEBUG_OTHER = False


def set_autominimize(a = False):
    global is_autominimize
    is_autominimize = a


def isLocked():
    if sys.platform in ['linux', 'linux2']:
        # ["pgrep", "-cf", "lockscreen-mode"] has high latency (possibly)
        a = subprocess.check_output(['qdbus', 'com.canonical.Unity', '/com/canonical/Unity/Session', 'com.canonical.Unity.Session.IsLocked'])
        # print(a)
        if b'true' in a:
            DEBUG_OTHER and print('isSessionLocked() = true')
            return True
        elif b'false' in a:
            DEBUG_OTHER and print('isSessionLocked() = false')
            return False
    elif sys.platform in ['Windows', 'win32', 'cygwin']:
        # TODO TESTERS
        import ctypes
        ctypes.windll.user32.LockWorkStation()
    elif sys.platform in ['Mac', 'darwin', 'os2', 'os2emx']:
        # TODO
        pass
    pass


def isSessionLocked2():
    # TODO TESTERS
    if sys.platform in ['linux', 'linux2']:
        try:
            subprocess.check_output(["pgrep", "-cf", "lockscreen-mode"]).decode('utf-8').strip()
            print('isSessionLocked2 = true')
            return True
        except Exception:
            print('isSessionLocked2 = false')
            return False
    pass


def doLock():
    if sys.platform in ['linux', 'linux2']:
        # subprocess.Popen(['dm-tool', 'lock'])  # is bad (multiple lock, no sound after lock)
        # subprocess.Popen(["gnome-screensaver-command", "-l"]) # is ok

        # вот это проверь ещё:
        # $!(sleep 10s ;  xset dpms force suspend) & xdg-screensaver lock
        # и это:
        # dm-tool switch-to-greeter

        subprocess.Popen(['dbus-send', '--type=method_call', '--dest=org.gnome.ScreenSaver', '/org/gnome/ScreenSaver', 'org.gnome.ScreenSaver.Lock'])  # faster (proof?)

    elif sys.platform in ['Windows', 'win32', 'cygwin']:
        import ctypes
        ctypes.windll.user32.LockWorkStation()

    elif sys.platform in ['Mac', 'darwin', 'os2', 'os2emx']:
        # TODO https://superuser.com/questions/497207/how-can-i-tell-if-the-lock-screen-is-active-from-the-command-line-on-os-x
        pass

    else:
        print('sys.platform={platform} is unknown. Please report.'.format(platform=sys.platform))
        print(sys.version)


def isTargetMinimized_minimize():
    while gtk.events_pending():
        gtk.main_iteration()
    windows = screen.get_windows()
    active = screen.get_active_window()
    # if active is not None:
    #     print('Active window name="{}", group="{}"'.format(active.get_name(), active.get_class_group_name()))

    # TODO: rewrite in c++ or find solution of this
    """
    [xcb] Unknown sequence number while processing queue
    [xcb] Most likely this is a multi-threaded client and XInitThreads has not been called
    [xcb] Aborting, sorry about that.
    python3.5: ../../src/xcb_io.c:259: poll_for_event: Assertion `!xcb_xlib_threads_sequence_lost' failed.
    """
    """ WTF!!! запускаем, ждём счётчик, переключаемся альтабом или мышью (хз) и вылетает с такой парашей:
    [xcb] Unknown request in queue while dequeuing
    [xcb] Most likely this is a multi-threaded client and XInitThreads has not been called
    [xcb] Aborting, sorry about that.
    python3.5: ../../src/xcb_io.c:165: dequeue_pending_request: Assertion `!xcb_xlib_unknown_req_in_deq' failed.
    """
    # n = str(w.get_name())
    # if any(n in s for s in target_name):
    try:
        # https://lazka.github.io/pgi-docs/Wnck-3.0/classes/Window.html
        for w in windows:
            if w is None:
                continue
            for x in target_name:  # regexp support
                if re.match(x, str(w.get_name())) is not None:
                    if not w.is_minimized():
                        if is_autominimize and active is not None and w != active:
                            w.minimize()
                        return False
            if any(str(w.get_class_group_name()) in s for s in target_group):
                if not w.is_minimized():
                    if is_autominimize and active is not None and w != active:
                        w.minimize()
                    return False
            if any(str(w.get_xid()) in s for s in target_xid):
                if not w.is_minimized():
                    if is_autominimize and active is not None and w != active:
                        w.minimize()
                    return False
    except Exception as e:
        print("Error: "+str(e))
        return False
    return True


class Worker(QObject):
    finished = pyqtSignal()
    setIconText = pyqtSignal(str)

    @pyqtSlot()
    def procCounter(self):
        t = -incubation_period
        # max_t = int(sys.argv[1])

        while True:
            time.sleep(delay)

            if isLocked():
                # if not isSessionLocked2():
                #     print("они не одинаковы, мой лучше")
                t = -incubation_period
                continue
            else:
                if not isTargetMinimized_minimize():
                    t += delay  # FIXME time()-t1
                    disp = int(lock_after-(math.floor(t)))
                    self.setIconText.emit(str(disp))
                else:
                    if t<0:
                        t += delay
                        disp = int(lock_after-(math.floor(t)))
                        self.setIconText.emit(str(disp))
                    else:
                        self.setIconText.emit('')

            if t >= lock_after:
                doLock()
                t = 0.


def quit_app():
    print("All is ok.")
    doLock()
    exit()


class SystemTrayIcon(QSystemTrayIcon):
    margin = (1, 1)
    size = (21, 21)  # хотя говорится о цифре 22 на 22
    # size = (22, 22)
    color_text = (222,222,222,0)
    mode = 'RGBA'
    
    icon_idle = None
    icon_counter = None
    icon = None

    def add_xid(self):
        global target_xid
        while gtk.events_pending():
            gtk.main_iteration()
        active = screen.get_active_window()
        if active is not None:
            xid = str(active.get_xid())
            if any(xid in s for s in target_xid):
                target_xid.remove(xid)
                doLock()
            else:
                target_xid.append(xid)

    def reset_xid(self):
        global target_xid
        target_xid = []
        doLock()

    def add_group(self):
        global target_group
        while gtk.events_pending():
            gtk.main_iteration()
        active = screen.get_active_window()
        if active is not None:
            xid = str(active.get_xid())
            if any(xid in s for s in target_group):
                target_group.remove(xid)
                doLock()
            else:
                target_group.append(xid)

    def show_info(self):
        while gtk.events_pending():
            gtk.main_iteration()
        active = screen.get_active_window()
        if active is not None:
            self.showMessage("Class: "+str(active.get_class_group_name()), "Name: "+str(active.get_name()), self.NoIcon, 1)

    def __init__(self, icon, parent=None):
        QSystemTrayIcon.__init__(self, icon, parent)
        menu = QMenu(parent)

        self.icon_counter = Image.open('gerald.png')
        self.icon_counter.thumbnail(self.size, Image.ANTIALIAS)

        icon_idle = Image.open('gerald2.png')
        icon_idle.thumbnail(self.size, Image.ANTIALIAS)
        self.icon_idle = QIcon(QPixmap.fromImage(ImageQt(icon_idle)))
        # self.setIconText()  # redundant

        action_add_xid = menu.addAction("Add/remove XID")
        action_reset_xid = menu.addAction("Reset XID")
        action_add_group = menu.addAction("Add/remove Group")
        action_show_info = menu.addAction("Show active window info")
        action_toggle_autominimize = menu.addAction("Toggle autominimize")
        quitAction = menu.addAction("Quit Panika")

        action_add_xid.triggered.connect(self.add_xid)
        action_reset_xid.triggered.connect(self.reset_xid)
        action_add_group.triggered.connect(self.add_group)
        action_show_info.triggered.connect(self.show_info)
        action_toggle_autominimize.triggered.connect(lambda x: set_autominimize(not is_autominimize))
        quitAction.triggered.connect(quit_app)

        self.setContextMenu(menu)


        self.worker = Worker()
        self.thread = QThread()
        self.worker.setIconText.connect(self.setIconText)  # 2 - Connect Worker`s Signals to Form method slots to post data.
        self.worker.moveToThread(self.thread)  # 3 - Move the Worker object to the Thread object
        self.worker.finished.connect(self.thread.quit)  # 4 - Connect Worker Signals to the Thread slots
        self.thread.started.connect(self.worker.procCounter)  # 5 - Connect Thread started signal to Worker operational slot method
        self.thread.finished.connect(quit_app)
        self.thread.start()  # 6 - Start the thread
        pass

    curr = ''

    def setIconText(self, s=''):
        if self.curr != s:
            # print("curr="+self.curr+", s="+s)
            self.icon = copy.copy(self.icon_counter)
            if s and not (s is ''):
                draw = ImageDraw.Draw(self.icon)
                font = ImageFont.truetype('/usr/share/fonts/truetype/ubuntu-font-family/Ubuntu-L.ttf', 12)
                draw.text((self.margin[0]+2+(4 if len(s)<2 else 0), self.margin[1]+3), s, self.color_text, font=font)
                self.setIcon(QIcon(QPixmap.fromImage(ImageQt(self.icon))))
            else:
                self.setIcon(self.icon_idle)
            self.curr = s


def main():
    app = QApplication(sys.argv)

    w = QWidget()
    trayIcon = SystemTrayIcon(QIcon("gerald2.png"), w)

    trayIcon.show()
    app.exec_()

if __name__ == '__main__':
    main()
