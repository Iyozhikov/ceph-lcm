# -*- coding: utf-8 -*-
# Copyright (c) 2017 Mirantis Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Base health checker"""


import asyncio
import collections
import os
import threading

import asyncssh

from decapod_common import log


LOG = log.getLogger(__name__)
"""Logger."""


ExecuteTaskResult = collections.namedtuple(
    "ExecuteTaskResult", ["ok", "errors", "cancelled"])


class Connections:

    def __init__(self, private_key, event_loop):
        self.connections = {}
        self.private_key = private_key
        self.lock = threading.RLock()
        self.event_loop = event_loop

    async def get(self, srv):
        key = srv.model_id

        if key in self.connections:
            return self.connections[key]

        with self.lock:
            if key not in self.connections:
                self.connections[key] = await self.make_connection(srv)

            return self.connections[key]

    async def make_connection(self, srv):
        return await asyncssh.connect(
            srv.ip,
            known_hosts=None,
            username=srv.username,
            client_keys=[self.private_key],
            loop=self.event_loop
        )

    async def async_close(self):
        coros = []

        for value in self.connections.values():
            value.close()
            coros.append(value.wait_closed())

        if coros:
            await asyncio.wait(coros)

    def close(self):
        self.event_loop.run_until_complete(self.async_close())


class Task:

    def __init__(self, connections, srv):
        self.srv = srv
        self.connections = connections
        self.exception = None

    async def run(self):
        return self

    async def get_connection(self):
        return await self.connections.get(self.srv)

    @property
    def name(self):
        return self.srv.model_id

    @property
    def ok(self):
        return not bool(self.exception)

    @property
    def completed(self):
        return bool(self.exception)


class CommandTask(Task):

    @staticmethod
    def get_bytes(text):
        return text.encode("utf-8") if isinstance(text, str) else text

    @staticmethod
    def get_str(text):
        return text if isinstance(text, str) else text.decode("utf-8")

    def __init__(self, connections, srv, cmd):
        super().__init__(connections, srv)

        self.cmd = cmd
        self.result = None

    async def run(self):
        connection = await self.get_connection()
        self.result = await connection.run(self.cmd, check=True)
        return self

    @property
    def completed(self):
        return self.result is not None

    @property
    def ok(self):
        return self.code == os.EX_OK

    @property
    def code(self):
        if not self.completed:
            return -1
        return self.result.exit_status

    @property
    def stdout_bytes(self):
        if not self.completed:
            return b""
        return self.get_bytes(self.result.stdout)

    @property
    def stdout_text(self):
        if not self.completed:
            return ""
        return self.get_str(self.result.stdout)

    @property
    def stdout_lines(self):
        return self.stdout_text.splitlines()

    @property
    def stderr_bytes(self):
        if not self.completed:
            return b""
        return self.get_bytes(self.result.stderr)

    @property
    def stderr_text(self):
        if not self.completed:
            return ""
        return self.get_str(self.result.stderr)

    @property
    def stderr_lines(self):
        return self.stderr_text.splitlines()


class Check:

    def __init__(self, connections, cluster, batch_size, event_loop):
        self.cluster = cluster
        self.connections = connections
        self.batch_size = batch_size
        self.event_loop = event_loop

    def verify(self):
        try:
            return self.event_loop.run_until_complete(self.run())
        except Exception as exc:
            LOG.error(
                "Cluster %s has failed check: %s",
                self.cluster.model_id, exc)
            raise exc

    async def run(self):
        pass

    async def execute_tasks(self, *tasks):
        to_run = [
            (tsk, asyncio.ensure_future(tsk.run()))
            for tsk in tasks
        ]
        await asyncio.wait([future for _, future in to_run])

        ok, errors, cancelled = [], [], []
        for tsk, future in to_run:
            if future.cancelled():
                cancelled.append(tsk)
            elif future.exception():
                tsk.exception = future.exception()
                errors.append(tsk)
            else:
                ok.append(tsk)

        return ExecuteTaskResult(ok, errors, cancelled)

    async def execute_cmd(self, cmd, *servers):
        if not servers:
            return []

        tasks = [CommandTask(self.connections, srv, cmd) for srv in servers]
        cmd = cmd.strip()
        if not cmd.startswith("sudo"):
            cmd = "sudo -EHn -- {0}".format(cmd)

        return await self.execute_tasks(*tasks)

    def server_iter(self):
        batch_size = self.batch_size
        all_servers = list(self.servers)

        if not self.batch_size or self.batch_size < 0:
            batch_size = len(self.servers)

        while all_servers:
            yield all_servers[:batch_size]
            all_servers = all_servers[batch_size:]
