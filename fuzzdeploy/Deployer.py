import datetime
import os
import signal
import sys
import time

import psutil

from . import utility


class Deployer:
    @staticmethod
    def cpu_allocate(self):
        CPU_RANGE = self.CPU_RANGE
        WORK_DIR_LOCK = self.WORK_DIR_LOCK
        while True:
            used_cpu_ls = os.listdir(WORK_DIR_LOCK)
            for cpu_id in CPU_RANGE:
                if cpu_id not in used_cpu_ls:
                    with open(os.path.join(WORK_DIR_LOCK, cpu_id), "x") as file:
                        pass
                    return cpu_id
            time.sleep(5)

    @staticmethod
    @utility.time_count("Fuzzing done")
    def start_fuzzing(
        WORK_DIR, FUZZERS, TARGETS, TIMEOUT, FUZZERS_ARGS, REPEAT=1, CPU_RANGE=None
    ):
        assert WORK_DIR is not None, "WORK_DIR should not be None"
        assert FUZZERS is not None, "FUZZERS should not be None"
        assert TARGETS is not None, "TARGETS should not be None"
        assert TIMEOUT is not None, "TIMEOUT should not be None"
        assert FUZZERS_ARGS is not None, "FUZZERS_ARGS should not be None"
        WORK_DIR = os.path.abspath(WORK_DIR)
        WORK_DIR_AR = os.path.join(WORK_DIR, "ar")
        if not isinstance(REPEAT, (list, tuple)):
            REPEAT = [REPEAT]
        REPEAT = [str(i) for i in REPEAT]
        if CPU_RANGE is not None:
            CPU_RANGE = [str(i) for i in CPU_RANGE]
        else:
            CPU_RANGE = [str(i) for i in range(psutil.cpu_count())]
        assert len(CPU_RANGE) > 0, "CPU_RANGE should contain one element at least"
        # init_workdir
        for fuzzer in FUZZERS:
            for target in TARGETS.keys():
                for index in REPEAT:
                    path = os.path.join(WORK_DIR_AR, fuzzer, target, index)
                    assert not os.path.exists(
                        path
                    ), f"{path} already exists, remove it or change REPEAT"
                    os.makedirs(path)
        utility.console.print(
            f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {WORK_DIR} init"
        )
        # start fuzzing
        for fuzzer in FUZZERS:
            for target in TARGETS.keys():
                assert (
                    utility.get_cmd_res(
                        f'docker images --format "{{{{.Repository}}}}" | grep -q "^{fuzzer}/{target}"'
                    )
                    != None
                ), utility.console.print(f"docker image {fuzzer}/{target} not found")
        container_id_dict = {}

        def sigint_handler(signal, frame):
            utility.console.print()
            with utility.console.status(
                f"[bold green]interrupted by user, docker containers removing...",
                spinner="arrow3",
            ) as status:
                for container_id in container_id_dict.keys():
                    utility.get_cmd_res(f"docker rm -f {container_id}")
            utility.console.print(
                f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} interrupted by user, \
docker containers removed"
            )
            utility.console.print(f"The results can be found in {WORK_DIR_AR}")
            sys.exit()

        signal.signal(signal.SIGINT, sigint_handler)

        free_cpu_ls = CPU_RANGE
        for index in REPEAT:
            for fuzzer in FUZZERS:
                for target in TARGETS.keys():
                    while len(free_cpu_ls) == 0:
                        for container_id in list(container_id_dict.keys()):
                            if not utility.is_container_running(container_id):
                                free_cpu_ls.append(container_id_dict.pop(container_id))
                        time.sleep(10)
                    cpu_id = free_cpu_ls.pop(0)
                    container_id = utility.get_cmd_res(
                        f"""
        docker run \
        -itd \
        --rm \
        --volume={os.path.join(WORK_DIR_AR, fuzzer, target, index)}:/shared \
        --cap-add=SYS_PTRACE \
        --security-opt seccomp=unconfined \
        --cpuset-cpus="{cpu_id}" \
        --env=CPU_ID={cpu_id} \
        --env=FUZZER_ARGS="{FUZZERS_ARGS[fuzzer][target]}" \
        --env=TAEGET_ARGS="{TARGETS[target]}" \
        --env=TIMEOUT="{TIMEOUT}" \
        --network=none \
        --privileged \
        "{fuzzer}/{target}" \
        -c '${{SRC}}/run.sh'
                        """
                    ).strip()
                    container_id_dict[container_id] = cpu_id
                    utility.console.print(
                        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        container_id[:12].ljust(12),
                        fuzzer.ljust(16),
                        target.ljust(10),
                        index.ljust(3),
                        "starts on cpu",
                        cpu_id,
                    )
        for container_id in container_id_dict.keys():
            utility.get_cmd_res(f"docker wait {container_id} 2> /dev/null")
        utility.console.print(
            f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} All DONE!"
        )
        utility.console.print(f"The results can be found in {WORK_DIR_AR}")
