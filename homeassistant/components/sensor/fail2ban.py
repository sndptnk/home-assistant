"""
Support for displaying IPs banned by fail2ban.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/sensor.fail2ban/
"""
import os
import logging

from datetime import timedelta

import re
import voluptuous as vol

import homeassistant.helpers.config_validation as cv
import homeassistant.util.dt as dt_util
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    CONF_NAME, CONF_SCAN_INTERVAL, CONF_FILE_PATH
)
from homeassistant.helpers.entity import Entity

_LOGGER = logging.getLogger(__name__)

CONF_JAILS = 'jails'

DEFAULT_NAME = 'fail2ban'
DEFAULT_LOG = '/var/log/fail2ban.log'
SCAN_INTERVAL = timedelta(seconds=120)

STATE_CURRENT_BANS = 'current_bans'
STATE_ALL_BANS = 'total_bans'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_JAILS): vol.All(cv.ensure_list, vol.Length(min=1)),
    vol.Optional(CONF_FILE_PATH): cv.isfile,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
})


async def async_setup_platform(hass, config, async_add_entities,
                               discovery_info=None):
    """Set up the fail2ban sensor."""
    name = config.get(CONF_NAME)
    jails = config.get(CONF_JAILS)
    scan_interval = config.get(CONF_SCAN_INTERVAL)
    log_file = config.get(CONF_FILE_PATH, DEFAULT_LOG)

    device_list = []
    log_parser = BanLogParser(scan_interval, log_file)
    for jail in jails:
        device_list.append(BanSensor(name, jail, log_parser))

    async_add_entities(device_list, True)


class BanSensor(Entity):
    """Implementation of a fail2ban sensor."""

    def __init__(self, name, jail, log_parser):
        """Initialize the sensor."""
        self._name = '{} {}'.format(name, jail)
        self.jail = jail
        self.ban_dict = {STATE_CURRENT_BANS: [], STATE_ALL_BANS: []}
        self.last_ban = None
        self.log_parser = log_parser
        self.log_parser.ip_regex[self.jail] = re.compile(
            r"\[{}\].(Ban|Unban) ([\w+\.]{{3,}})".format(re.escape(self.jail))
        )
        _LOGGER.debug("Setting up jail %s", self.jail)

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state_attributes(self):
        """Return the state attributes of the fail2ban sensor."""
        return self.ban_dict

    @property
    def state(self):
        """Return the most recently banned IP Address."""
        return self.last_ban

    def update(self):
        """Update the list of banned ips."""
        if self.log_parser.timer():
            self.log_parser.read_log(self.jail)

        if self.log_parser.data:
            for entry in self.log_parser.data:
                _LOGGER.debug(entry)
                current_ip = entry[1]
                if entry[0] == 'Ban':
                    if current_ip not in self.ban_dict[STATE_CURRENT_BANS]:
                        self.ban_dict[STATE_CURRENT_BANS].append(current_ip)
                    if current_ip not in self.ban_dict[STATE_ALL_BANS]:
                        self.ban_dict[STATE_ALL_BANS].append(current_ip)
                    if len(self.ban_dict[STATE_ALL_BANS]) > 10:
                        self.ban_dict[STATE_ALL_BANS].pop(0)

                elif entry[0] == 'Unban':
                    if current_ip in self.ban_dict[STATE_CURRENT_BANS]:
                        self.ban_dict[STATE_CURRENT_BANS].remove(current_ip)

        if self.ban_dict[STATE_CURRENT_BANS]:
            self.last_ban = self.ban_dict[STATE_CURRENT_BANS][-1]
        else:
            self.last_ban = 'None'


class BanLogParser:
    """Class to parse fail2ban logs."""

    def __init__(self, interval, log_file):
        """Initialize the parser."""
        self.interval = interval
        self.log_file = log_file
        self.data = list()
        self.last_update = dt_util.now()
        self.ip_regex = dict()

    def timer(self):
        """Check if we are allowed to update."""
        boundary = dt_util.now() - self.interval
        if boundary > self.last_update:
            self.last_update = dt_util.now()
            return True
        return False

    def read_log(self, jail):
        """Read the fail2ban log and find entries for jail."""
        self.data = list()
        try:
            with open(self.log_file, 'r', encoding='utf-8') as file_data:
                self.data = self.ip_regex[jail].findall(file_data.read())

        except (IndexError, FileNotFoundError, IsADirectoryError,
                UnboundLocalError):
            _LOGGER.warning("File not present: %s",
                            os.path.basename(self.log_file))