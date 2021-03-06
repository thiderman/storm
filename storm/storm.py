#!/usr/bin/env python -u

import os
import re
import sys
import time
import glob
import socket
import threading
import datetime
import asyncore
import subprocess as sub
import pyinotify as inf

from os.path import join
from collections import defaultdict

import alsaaudio
import psutil
import logbook

from storm import conf
from storm import cloud
from storm import util


logger = logbook.Logger('root')


class StormFormatter(util.LoggedClass):
    def __init__(self):
        self.colors = conf.CONFIG['colors']

        # XXX: Will only work if ran from bin/storm. Iz problem?
        self.icons = os.path.abspath(
            join(sys.argv[0], '..', '..', 'storm', 'icons')
        )

        super().__init__()

    def colorize(self, text, fg=None, bg=None):
        fg = self.colors[fg] if fg else self.colors["fg_1"]
        bg = self.colors[bg] if bg else self.colors["bg_1"]
        return "^fg(%s)^bg(%s)%s^fg()^bg()" % (fg, bg, text)

    def icon(self, icon, fg=None, bg=None):
        if fg is None:
            fg = "icon"
        icon = "^i(%s)" % join(self.icons, "%s.xbm" % icon)

        return "%s" % self.colorize(icon, fg=fg, bg=bg)

    def tags(self, data):
        """
        Example data to be a tab separated string:

        data = "\t:1\t#2\t.3\t.4\t.5"

        """
        tags = ""
        for tag in data.split('\t'):
            if len(tag) == 0 or tag[:1] == '\n':
                continue
            else:
                state = tag[0]
                tag = tag[1:]

            if state == "#":
                # Active tag
                tag_design = self.colorize(" %s " % tag, fg="bg_1", bg="fg_3")
            elif state == "+":
                # Urgent tag
                tag_design = self.colorize(" %s " % tag, fg="bg_1", bg="crit")
            elif state == "!":
                # Urgent tag
                tag_design = self.colorize(" %s " % tag, fg="bg_1", bg="crit")
            elif state == ".":
                # Emtpty tag
                continue
            else:
                # Regular ol' tag
                tag_design = self.colorize(" %s " % tag)

            ctl = "^ca(1,herbstclient focus_monitor 0 && "
            ctl += "herbstclient use %s)%s^ca()"
            tags += ctl % (
                tag,
                tag_design
            )

        return tags

    def windowtitle(self, data):
        """
        Example data to be a string:

        data = "main@rey"

        """
        return self.colorize(data)

    def date(self, data):
        """
        Example data to be a dict:

        data = {
            "day": "Mon",
            "date": 2013.09.02",
            "time": "19:23:52"
        }

        """
        return "%s %s %s %s" % (
            self.colorize(data['day']),
            self.colorize(data['date']),
            self.colorize("@", fg="fg_3"),
            self.colorize(data['time'])
        )

    def network(self, data):
        """
        Example data to be a string:

        data = "192.168.1.23" or data = "N/A"

        """
        if data == "N/A":
            ip = self.colorize(data, "dead")
            icon = self.icon("wifi_01", fg="dead")
        else:
            ip = self.colorize(data)
            icon = self.icon("wifi_01")

        return "%s %s" % (icon, ip)

    def load(self, data):
        """
        Example data to be a list:

        data = [0.22, 0.24, 0.23]

        """
        load_avgs = ""
        elevation = False
        for avg in data:
            if avg < 1:
                load_avgs += "%s " % self.colorize("%.2f" % avg)
            elif avg < 3:
                load_avgs += "%s " % self.colorize("%.2f" % avg, fg="warn")
                if elevation != "crit":
                    elevation = "warn"
            else:
                load_avgs += "%s " % self.colorize("%.2f" % avg, fg="crit")
                elevation = "crit"

            icon = self.icon("scorpio")
            if elevation:
                icon = self.icon("scorpio", fg=elevation)

        return "%s %s" % (icon, load_avgs[:-1])

    def processes(self, data):
        """
        Example data to be a int:

        data = 161

        """
        if data < 300:
            processes = self.colorize(data)
            icon = self.icon("cpu")
        elif data < 600:
            processes = self.colorize(processes, "warn")
            icon = self.icon("cpu", fg="warn")
        else:
            processes = self.colorize(processes, "crit")
            icon = self.icon("cpu", fg="warn")

        return "%s %s" % (icon, processes)

    def mem_swap(self, data):
        """
        Example data to be a dict:

        data = {
            "memory": 663,
            "swap": 0
        }

        """
        return "%s %s%s%s" % (
            self.icon("mem"),
            self.colorize(int(data["memory"] / 1024**2), fg="fg_2"),
            self.colorize("/", fg="fg_1"),
            self.colorize(int(data["swap"] / 1024**2), fg="fg_2")
        )

    def packages(self, data):
        """
        Example data to be a dict:

        data = {
            "installed": 663,
            "new": 0
        }

        """
        return "%s %s%s%s" % (
            self.icon("pacman"),
            self.colorize(data["installed"]),
            self.colorize("/", fg="fg_3"),
            self.colorize(data["new"])
        )

    def volume(self, data):
        """
        Example data to be a dict:

        data = {
            "volume": 71,
            "muted": False
        }

        """
        if data["volume"] < 35:
            icon = self.icon("spkr_02")
        else:
            icon = self.icon("spkr_01")

        if data["muted"]:
            volume = "%s %s" % (
                self.colorize("%s%%" % data["volume"], fg="fg_2"),
                self.colorize("(Mute)", fg="dead")
            )
        else:
            volume = self.colorize("%s%%" % data["volume"])

        return "%s %s" % (icon, volume)

    def hostname(self, data):
        """
        Example data to be a string:

        data = "rey"

        """
        return self.colorize(socket.gethostname())

    def kernel(self, data):
        """
        Example data to be a string:

        data = "2.10.9-1-ARCH"

        """
        return "%s %s" % (
            self.icon("arch"),
            data
        )

    def power(self, data):
        """
        Example data to be a dict:

        data = {
            "percent": 31,
            "ac_connected": False,
            "time_left": "01:26"
        }

        """
        percent = data["percent"]
        fg = None
        icon_fg = None

        if percent < 10:
            icon = "bat_empty_01",
            icon_fg = "crit"
            fg = "crit"
        elif percent < 20:
            icon = "bat_empty_01",
            icon_fg = "warn"
            fg = "warn"
        elif percent < 30:
            icon = "bat_low_01",
            icon_fg = "warn"
        elif percent < 50:
            icon = "bat_low_01"
        elif percent < 80:
            icon = "bat_full_01"
        else:
            icon = "bat_full_01"
            fg = "fg_3"

        if data["ac_connected"]:
            icon = 'ac_01'

        ret = "{0} {1}".format(
            self.icon(icon, fg=icon_fg),
            self.colorize(str(percent) + "%", fg=fg)
        )

        if data["time_left"]:
            ret += " ({0})".format(self.colorize(data["time_left"], "fg_2"))

        return ret

    def mail(self, data):
        return "%s %s" % (self.icon('mail'), self.colorize(data))


class StfuFormatter():
    pass


class Hooker():
    def __init__(self):
        self.hookers = defaultdict(set)

    def interval(self, sleep):
        def real_decorator(function):
            def wrapper(self, *args, **kwargs):
                while True:
                    ret = function(self)

                    fn = function.__name__
                    self.write(fn, ret, sleep > 5)

                    time.sleep(sleep)

            wrapper.runner = True
            return wrapper
        return real_decorator

    def hlwm(self, hook):
        def real_decorator(function):
            fn = function.__name__

            def wrapper(storm, *args, **kwargs):
                process = sub.Popen(
                    ['herbstclient', '--idle'],
                    stdout=sub.PIPE
                )
                while True:
                    output = process.stdout.readline()
                    if not output:
                        break

                    output = output.decode().replace('\n', '')
                    parts = output.split('\t')

                    if parts[0] in self.hookers[fn]:
                        hc_hook = []
                        for part in parts:
                            if len(part) > 0:
                                hc_hook.append(part)

                        ret = function(storm, hc_hook)
                        storm.write(fn, ret)

            # Store the hook name on the hooker object so that we can re-use
            # the same decorator for multiple hooks
            self.hookers[fn].add(hook)

            # Also, keep the original name for the decorator function so that
            # the line above does not get the function 'wrapper' for the next
            # run.
            wrapper.__name__ = fn
            wrapper.runner = True
            return wrapper
        return real_decorator

    def static(self, function):
        def wrapper(self, *args, **kwargs):
            ret = function(self)

            fn = function.__name__
            self.write(fn, ret)

        wrapper.runner = True
        return wrapper

    def inotify(self, path, mask):
        def real_decorator(function):
            class EventHandler(inf.ProcessEvent):
                def __init__(self, storm, *args, **kwargs):
                    self.storm = storm
                    super().__init__(*args, **kwargs)

                def process_default(self, event):
                    ret = function(self.storm)
                    fn = function.__name__
                    self.storm.write(fn, ret)

            def wrapper(self, *args, **kwargs):
                wm = inf.WatchManager()
                inf.AsyncNotifier(wm, EventHandler(self))
                wm.add_watch(path, mask, rec=True)
                asyncore.loop()

            wrapper.runner = True
            return wrapper
        return real_decorator


class Storm(util.LoggedClass):
    hooker = Hooker()

    def __init__(self, formatter):
        self.formatter = formatter
        self.monitor = "0"
        super().__init__()

    def setup(self):
        xdg = os.getenv(
            'XDG_CACHE_HOME',
            join(os.getenv('HOME'), '.cache')
        )
        self.log.debug('Got xdg root: {0}', xdg)

        p = join(xdg, 'storm')
        os.makedirs(p, exist_ok=True)
        self.cwd = p

        # self.checkhost = "google.com"
        # self.pac_count = "/dev/shm/fakepacdb/counts"

    def run(self):
        self.log.debug('Starting')
        # TODO: Unhack this from dir() pls :(
        for name in dir(self):
            value = getattr(self, name)
            if hasattr(value, 'runner'):
                t = threading.Thread(None, value)
                t.daemon = False
                t.start()

    def write(self, fn, data, output=True):
        if output:
            self.log.info("Writing {0}", fn)

        if hasattr(self.formatter, fn):
            func = getattr(self.formatter, fn)
            data = func(data)

        path = join(self.cwd, fn)
        with open(path, 'w') as fp:
            fp.write(str(data))

    @hooker.hlwm("tag_flags")
    @hooker.hlwm("tag_changed")
    def tags(self, hook):
        output = sub.Popen(
            ['herbstclient', 'tag_status'],
            stdout=sub.PIPE
        ).communicate()[0].decode()
        return output

    @hooker.hlwm("window_title_changed")
    @hooker.hlwm("focus_changed")
    def windowtitle(self, hook):
        ret = ""
        if len(hook) > 2:
            ret = hook[2]
        return ret

    @hooker.interval(1)
    def date(self):
        now = datetime.datetime.now()
        return {
            "day": now.strftime("%a,"),
            "date": now.strftime("%Y.%m.%d"),
            "time": now.strftime("%H:%M:%S")
        }

    # TODO: Use inotify on interface data
    @hooker.interval(20)
    def network(self):
        try:
            ip = socket.gethostbyname(socket.gethostname())
            # TODO: Please fix
            if "127.0.0" in ip:
                raise OSError
        except (OSError, Exception):
            ip = "N/A"

        return ip

    @hooker.interval(7)
    def load(self):
        return os.getloadavg()

    @hooker.interval(5)
    def processes(self):
        return len(psutil.get_pid_list())

    @hooker.interval(5)
    def mem_swap(self):
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        return {
            "memory": mem.free,
            "swap": swap.used
        }

    @hooker.interval(600)
    def packages(self):
        fakedb = join("/dev", "shm", "fakepacdb")
        fakelock = join(fakedb, "db.lck")
        # realdb = join("/var", "lib", "pacman")

        os.makedirs(join(fakedb, "sync"), exist_ok=True)

        if os.path.exists(fakelock):
            os.remove(join(fakedb, "db.lck"))

        # if not os.path.islink(join(fakedb, "local")):
            # os.symlink(join(realdb, "local"), fakedb)

        sub.Popen(
            ['fakeroot', 'pacman', '--dbpath', fakedb, '-Sy'],
            stdout=sub.DEVNULL
        ).communicate()

        pkgs = sub.Popen(
            ['pacman', '-Q'],
            stdout=sub.PIPE
        ).communicate()[0].decode()
        pkgs = len(pkgs.split("\n")) if len(pkgs) > 0 else 0

        new_pkgs = sub.Popen(
            ['pacman', '--dbpath', fakedb, '-Qqu'],
            stdout=sub.PIPE
        ).communicate()[0].decode()
        new_pkgs = len(new_pkgs.split("\n")) if len(new_pkgs) > 0 else 0

        return {
            "installed": pkgs,
            "new": new_pkgs
        }

        mixer = alsaaudio.Mixer(conf.CONFIG['volume']['mixer'])
        master = alsaaudio.Mixer()
        return {
            "volume": mixer.getvolume()[0],
            "muted": master.getmute()[0]
        }

    @hooker.static
    def hostname(self):
        return socket.gethostname()

    @hooker.static
    def kernel(self):
        out = sub.Popen(['uname', '-r'], stdout=sub.PIPE).communicate()
        kernel = str(re.sub(r'\s', '', out[0].decode()))
        return kernel

    @hooker.interval(10)
    def power(self):
        acpi = sub.Popen(['acpi', '-ab'], stdout=sub.PIPE)
        acpi = acpi.communicate()[0].decode().strip().split("\n")

        batteries = []
        for acpi_line in filter(lambda x: x.startswith('Battery'), acpi):
            bat = util.AcpiBattery(acpi_line)
            bat.parse()
            batteries.append(bat)

        percents = [b.percent for b in batteries]
        percent = sum(percents) / len(percents)
        total = sum(b.time.seconds for b in batteries)

        return {
            "percent": percent,
            "ac_connected": "on-line" in acpi[-1],
            "time_left": util.time_left(total)
        }

    @hooker.inotify(conf.CONFIG['mail']['mailroot'], inf.IN_MODIFY)
    def mail(self):
        mail = glob.glob(join(conf.CONFIG['mail']['mailroot'], '*/*/new/*'))
        mail = filter(lambda m: '/archive/' not in m, mail)
        return len(list(mail))


def main():
    if len(sys.argv) > 1:
        # Argument given, start the cloudz!
        logger.info('Summoning clouds...')
        cloud.main()
        sys.exit(0)

    def cloud_thread():
        font = "-*-montecarlo-medium-*-*-*-11-*-*-*-*-*-*-*"

        p1 = sub.Popen([sys.argv[0], 'cloud'], stdout=sub.PIPE, bufsize=0)
        p2 = sub.Popen(
            [
                'dzen2', '-dock', '-ta', 'l', '-sa', 'rc',
                '-fn', font, '-h', '17'
            ],
            bufsize=0,
            stdin=p1.stdout,
            stderr=sub.PIPE,
            stdout=sub.PIPE,
        )
        # p1.stdout.close()

        # Will run 5eva
        logger.info('Starting dem cloud')
        p2.wait()

    def storm_thread():
        logger.info('Conjuring the storm...')
        formatter = StormFormatter()
        # formatter = StfuFormatter()
        storm = Storm(formatter)
        storm.setup()
        storm.run()

    ct = threading.Thread(None, cloud_thread)
    ct.daemon = False
    ct.start()

    st = threading.Thread(None, storm_thread)
    st.daemon = False
    st.start()


if __name__ == '__main__':
    main()
