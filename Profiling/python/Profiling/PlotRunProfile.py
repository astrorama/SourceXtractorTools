#
# Copyright (C) 2012-2020 Euclid Science Ground Segment
#
# This library is free software; you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the Free
# Software Foundation; either version 3.0 of the License, or (at your option)
# any later version.
#
# This library is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this library; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
#

import argparse
import os
from datetime import timedelta

import ElementsKernel.Logging as logging
import matplotlib.pyplot as plt
import numpy as np
from dateutil.parser import parse, parser as dateutil_parser
from matplotlib.ticker import FuncFormatter
from time import mktime

logger = logging.getLogger(__name__)


def _parse_sourcex_logs(path):
    """
    Low level parsing of the logs
    :param path:
        SourceX logs
    :return:
        A dictionary with the log entries, with their timestamp, logger, level and message
    """
    timestamp_parser = dateutil_parser()

    log = dict(timestamp=[], logger=[], level=[], message=[])
    with open(path) as fd:
        for line in fd:
            try:
                timestamp, who, level, _, message = line.split(maxsplit=4)
                log['timestamp'].append(timestamp_parser.parse(timestamp))
                log['logger'].append(who)
                log['level'].append(level)
                log['message'].append(message.strip())
            except ValueError as e:
                logger.warning(e)
    start = log['timestamp'][0]
    log['Time'] = np.array([(t - start).seconds for t in log['timestamp']])
    return log


def read_sourcex_logs(path):
    """
    Parse SourceXtractor logs to extract and generate the relevant events
    """
    parsed = _parse_sourcex_logs(path)

    data = dict(
        background=[],
        segmentation=[None, None],
        deblending=[None, None],
        measurement=[None, None],
    )
    deblending_max = 0
    measured_max = 0
    for m, t in zip(parsed['message'], parsed['Time']):
        # Thread count
        if m.startswith('thread-count ='):
            data['thread-count'] = int(m.split('=')[1].strip())
        # Tile memory limit
        elif m.startswith('tile-memory-limit ='):
            data['tile-memory-limit'] = int(m.split('=')[1].strip())
        # Background modelling
        elif m.startswith('Background for image'):
            data['background'].append(t)
        # Segmentation
        elif m.startswith('Segmentation'):
            _, line, _, total, _ = m.split()
            # First line done, ~approximation for start
            if int(line) > 0 and data['segmentation'][0] is None:
                data['segmentation'][0] = t
            # Last line done, end
            if int(line) == int(total) and data['segmentation'][1] is None:
                data['segmentation'][1] = t
        # Measurement
        elif m.startswith('Measured'):
            # First done, ~approximation for start
            # Move end time until the counting does not increase
            aux = m.split()
            if len(aux) > 2:
                count = int(aux[1])
                if data['measurement'][0] is None:
                    data['measurement'][0] = t
                if count > measured_max:
                    data['measurement'][1] = t
                    measured_max = count
        # Deblending
        elif m.startswith('Deblended'):
            _, count = m.split()
            count = int(count)
            # First reported, ~approximation for start
            # Move end time until the counting does not increase
            if count > deblending_max:
                if deblending_max == 0:
                    data['deblending'][0] = t
                data['deblending'][1] = t
                deblending_max = count
    return data


def parse_time(v: str) -> float:
    """
    Time to a posix timestamp
    Depending on the pidstat version, must use a different method
    """
    try:
        return float(v)
    except ValueError:
        return mktime(parse(v).timetuple())


def read_pidstat(path, ncores=32):
    """
    Parse
    """
    data = dict()
    reading_values = False

    with open(path) as fd:
        for line in fd:
            if line[0] == '#':
                keys = line[1:].split()
                for k in keys:
                    if k not in data:
                        data[k] = []
                reading_values = True
            elif reading_values:
                values = line.split()
                for k, v in zip(keys, values):
                    try:
                        if k == 'Time':
                            data[k].append(parse_time(v))
                        else:
                            data[k].append(float(v))
                    except ValueError:
                        data[k].append(v)
    for k, v in data.items():
        data[k] = np.array(v)
    data['Time'] = data['Time'] - data['Time'][0]
    data['CPU'] = (data['%CPU'] / 100) * ncores
    return data


def _pretty_duration(timestamps):
    d = timedelta(seconds=float(timestamps[1] - timestamps[0]))
    return str(d)


def plot_perf(pidstat, log, cpu_config=32, ax=None, title=None):
    if ax is None:
        ax = plt.gca()

    lcpu = ax.plot(pidstat['Time'], pidstat['CPU'], label='CPU')
    lconfig = ax.axhline(cpu_config, color='red', linestyle='--', label='thread-number')
    lbg = ax.vlines(
        log['background'], 0, cpu_config, color='black', linestyle='--',
        label='Background done'
    )
    ls = ax.axvspan(
        *log['segmentation'], ymin=0, ymax=0.33, color='orange',
        label='Segmentation ({})'.format(_pretty_duration(log['segmentation']))
    )
    ld = ax.axvspan(
        *log['deblending'], ymin=0.33, ymax=0.66, color='pink',
        label='Deblending ({})'.format(_pretty_duration(log['deblending']))
    )
    lm = ax.axvspan(
        *log['measurement'], ymin=0.66, ymax=1., color='lightgreen',
        label='Measurement ({})'.format(_pretty_duration(log['measurement']))
    )
    ax.set_ylabel('Number of CPU')

    # Moving average
    ma = np.convolve(pidstat['CPU'], np.ones(60), 'same') / 60
    ax.plot(pidstat['Time'], ma, linestyle='-', color='cyan', alpha=0.5)

    formatter = FuncFormatter(lambda s, x: str(timedelta(seconds=s)))
    ax.xaxis.set_major_formatter(formatter)
    ax.set_xlabel('Time')

    lns = lcpu + [lconfig, lbg, ls, ld, lm]

    legend_ax = ax
    if 'RSS' in pidstat:
        ax2 = ax.twinx()
        legend_ax = ax2
        lio = ax2.plot(pidstat['Time'], pidstat['RSS'] / 1024, linestyle='-.', color='deeppink',
                       label='RSS')
        ax2.set_ylabel('MiB')
        tml = ax2.axhline(log['tile-memory-limit'], linestyle='--', color='gray', label='tile-memory-limit')
        lns.extend(lio)
        lns.append(tml)
    elif 'kB_rd/s' in pidstat:
        ax2 = ax.twinx()
        legend_ax = ax2
        lio = ax2.plot(pidstat['Time'], pidstat['kB_rd/s'] / 1024, linestyle=':', color='gray',
                       label='Read activity')
        ax2.set_ylabel('MB/s')
        lns.extend(lio)

    labels = [l.get_label() for l in lns]
    legend_ax.legend(lns, labels)
    ax.grid()
    if title:
        ax.set_title(title)


def defineSpecificProgramOptions():
    """
    @brief Allows to define the (command line and configuration file) options
    specific to this program

    @details
        See the Elements documentation for more details.
    @return
        An  ArgumentParser.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('-s', '--pidstat', type=str, required=True,
                        help='Output of `pidstat -I -h -d -u -p`')
    parser.add_argument('-l', '--log', type=str, required=True,
                        help='SourceXtractor log')
    parser.add_argument('-n', '--n-cores', type=int, default=None,
                        help='Number of cores on the machine. This is required to scale'
                             'accordingly the %CPU from pidstat')
    parser.add_argument('-t', '--title', type=str, default=None,
                        help='Plot title')
    return parser


def mainMethod(args):
    """
    @brief The "main" method.
    @details
        This method is the entry point to the program. In this sense, it is
        similar to a main (and it is why it is called mainMethod()).
    """
    sourcex_log = read_sourcex_logs(args.log)

    # Default to thread-count * 2, as done in lesta (thread-count configured to be 1 per core,
    # and each core has 2 hyper-threads)
    if not args.n_cores:
        args.n_cores = sourcex_log['thread-count'] * 2
    if not args.title:
        args.title = os.path.basename(args.log)

    pidstat = read_pidstat(args.pidstat, ncores=args.n_cores)
    plot_perf(pidstat, sourcex_log, cpu_config=sourcex_log['thread-count'], title=args.title)
    plt.show()
