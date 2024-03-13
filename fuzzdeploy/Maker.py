import os
import threading

import psutil

from . import utility
from .Builder import Builder
from .CpuAllocator import CpuAllocator


class Maker:
    @staticmethod
    def _make(WORK_DIRs, SUB, BASE, IS_SKIP, CPU_RANGE, ENV, MODE):
        # check if images exist
        TARGETS = set()
        for (
            fuzzer,
            target,
            repeat,
            repeat_path,
            work_dir,
        ) in utility.get_mul_workdir_paths_by(WORK_DIRs, "ar"):
            TARGETS.add(target)
        Builder.build_imgs(FUZZERS=[BASE], TARGETS=list(TARGETS))
        cpu_allocator = CpuAllocator(CPU_RANGE=CPU_RANGE)
        for (
            fuzzer,
            target,
            repeat,
            repeat_path,
            work_dir,
        ) in utility.get_mul_workdir_paths_by(WORK_DIRs, "ar"):
            if IS_SKIP and IS_SKIP(fuzzer, target, repeat, repeat_path, work_dir):
                continue
            ar_path = os.path.join(work_dir, "ar", fuzzer, target, repeat)
            dst_path = os.path.join(work_dir, SUB, fuzzer, target, repeat)
            os.makedirs(dst_path, exist_ok=True)
            # wait for a free cpu
            cpu_id = cpu_allocator.get_free_cpu()
            container_id = utility.get_cmd_res(
                f"""
            docker run \
            -itd \
            --rm \
            --volume={ar_path}:/shared \
            --volume={dst_path}:/{SUB} \
            --cap-add=SYS_PTRACE \
            --security-opt seccomp=unconfined \
            --cpuset-cpus="{cpu_id}" \
            {" ".join([f"--env={k}={v}" for k, v in ENV.items()])} \
            --network=none \
            "{BASE}/{target}" \
            -c '${{SRC}}/run.sh'
            """
            ).strip()
            cpu_allocator.append(container_id, cpu_id)
        while len(cpu_allocator.get_container_id_ls()) > 0:
            cpu_id = cpu_allocator.get_free_cpu()
            container_id_ls = cpu_allocator.get_container_id_ls()
            if len(container_id_ls) == 0:
                break
            if MODE == "ALL":
                container_id_dict = {
                    container_id: cpu_allocator.get_cpu_ls_by_container_id(container_id)
                    for container_id in container_id_ls
                }
                min_container_id = min(
                    container_id_dict, key=lambda k: len(container_id_dict[k])
                )
                allocated_cpu_ls = cpu_allocator.append(min_container_id, cpu_id)
                utility.get_cmd_res(
                    f"docker update --cpuset-cpus {','.join(allocated_cpu_ls)} {min_container_id} 2>/dev/null"
                )

    @staticmethod
    def make(
        WORK_DIRs,
        SUB,
        BASE,
        IS_SKIP: "function" = None,
        CPU_RANGE: "list" = None,
        ENV={},
        MODE: "PER | ALL" = "PER",
    ):
        if isinstance(WORK_DIRs, str):
            WORK_DIRs = [WORK_DIRs]
        for WORK_DIR in WORK_DIRs:
            assert os.path.exists(WORK_DIR), f"{WORK_DIR} not exists"
            ar_path = os.path.join(WORK_DIR, "ar")
            assert os.path.exists(ar_path), f"{ar_path} not exists"
        assert SUB is not None, "SUB should not be None"
        SUB = SUB.lower()
        assert BASE is not None, "BASE should not be None"
        available_cpu_count = psutil.cpu_count()
        if CPU_RANGE is None:
            if available_cpu_count > 1:
                available_cpu_count -= 1
            CPU_RANGE = [str(i) for i in range(available_cpu_count)]
        else:
            assert len(CPU_RANGE) > 0, "CPU_RANGE should contain one element at least"
            CPU_RANGE = [int(i) for i in CPU_RANGE]
            min_cpu = min(CPU_RANGE)
            max_cpu = max(CPU_RANGE)
            assert (
                min_cpu >= 0 and max_cpu < available_cpu_count
            ), f"available CPU_RANGE: 0-{available_cpu_count-1}"
            CPU_RANGE = [str(i) for i in CPU_RANGE]
        thread = threading.Thread(
            target=Maker._make,
            args=(WORK_DIRs, SUB, BASE, IS_SKIP, CPU_RANGE, ENV, MODE),
        )
        thread.setDaemon(True)
        thread.start()
        return thread
