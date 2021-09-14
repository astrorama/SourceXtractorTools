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
import json
import os
import subprocess
from shutil import which
from subprocess import Popen
from typing import List, Tuple

import time
from ElementsKernel.Exit import Code
from ElementsKernel.Logging import getLogger

logger = getLogger(__name__)


def findHighestVersion(project_area: str) -> str:
    """
    Find the highest version, or the folder with the highest priority
    """
    # Default names
    defaults = ['SourceXtractorPlusPlus', 'develop', 'master']
    for d in defaults:
        logger.info('Looking for working area %s', d)
        if os.path.exists(os.path.join(project_area, d)):
            return d
    # Find highest
    return None


def findInProjectArea(project_area: str, binary_tag: str, version: str) -> Tuple[str, dict]:
    """
    Return, if found, the path to sourcextractor++ and the environment to be used
    """
    build_dir = os.path.join(project_area, version, 'build.' + binary_tag)
    run_script = os.path.join(build_dir, 'run')
    logger.info('Checking existence of %s', run_script)
    if not os.path.exists(run_script):
        return None
    run_proc = subprocess.run([run_script, '--py'], capture_output=True, check=True, shell=False)
    env = eval(run_proc.stdout)
    return [os.path.join(build_dir, 'bin', 'sourcextractor++'), env]


def findBinary(project_area: str, binary_tag: str, version: str) -> Tuple[str, dict]:
    """
    Find the sourcextractor++ binary. It looks, in this order:
    1. Project area
        1.1 Given version if any
        1.2 If not, nested SourceXtractorPlusPlus, develop or master folder
        1.2 Highest version
    2. $PATH
    """
    if not version:
        version = findHighestVersion(project_area)
    sourcextractor = findInProjectArea(project_area, binary_tag, version)
    if sourcextractor:
        return sourcextractor
    return [which('sourcextractor++'), {}]


def runProfiled(sourcextractor: Tuple[str, dict], pidstat: str, log: str, interval: int,
                extra_args: List[str]):
    """
    Run sourcextractor, and attach pidstat to it
    """
    if os.path.exists(log):
        os.unlink(log)
    if os.path.exists(pidstat):
        os.unlink(pidstat)

    sourcex_bin, sourcex_env = sourcextractor
    sourcex_proc = Popen([sourcex_bin] + extra_args + ['--log-file', log], shell=False,
                         env=sourcex_env)
    logger.info('Running with PID %d', sourcex_proc.pid)
    # -h Output easy to parse
    # -I divide CPU usage by the total number of CPUs (otherwise some versions clip to 100%)
    # -d I/O
    # -u CPU utilization
    # -r memory
    with open(pidstat, 'wt') as pidstat_fd:
        pidstat_proc = Popen(['pidstat', '-hIdur', '-p', str(sourcex_proc.pid), str(interval)],
                             stdout=pidstat_fd)
        logger.info('Pidstat attached with PID %d', pidstat_proc.pid)
    sourcex_proc.wait()
    pidstat_proc.terminate()

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
    parser.add_argument('-u', '--use-version', type=str, default=None,
                        help='SourceXtractor++ version. '
                             'The script will try to figure it out if not specified')
    parser.add_argument('-p', '--project-area', type=str,
                        default=os.path.expandvars('${CMAKE_PROJECT_PATH}/SourceXtractorPlusPlus/'),
                        help='Location of SourceXtractor++ project area')
    parser.add_argument('-b', '--binary-tag', type=str, default=os.getenv('BINARY_TAG', ''),
                        help='Binary tag')
    parser.add_argument('--pidstat', type=str, default='pidstat.log',
                        help='pidstat output will be written here')
    parser.add_argument('--log', type=str, default='sourcextractor.log',
                        help='SourceXtractor log will be written here')
    parser.add_argument('-i', '--interval', type=int, default=5, help='Pidstat measure interval')
    parser.add_argument('args', metavar='ARG', type=str, nargs='*',
                        help='Will be forwarded directly to sourcextractor++')
    return parser


def mainMethod(args):
    """
    @brief The "main" method.
    @details
        This method is the entry point to the program. In this sense, it is
        similar to a main (and it is why it is called mainMethod()).
    """
    sourcextractor = findBinary(args.project_area, args.binary_tag, args.use_version)
    if not sourcextractor:
        logger.error('Could not find sourcextractor++')
        return Code['NOT_OK']
    logger.info('Using %s', sourcextractor[0])
    runProfiled(sourcextractor, args.pidstat, args.log, args.interval, args.args)
