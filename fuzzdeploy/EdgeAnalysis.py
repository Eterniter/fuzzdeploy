import csv
import json
import os

from . import utility
from .Builder import Builder
from .constants import *
from .CPUAllocator import CPUAllocator


class EdgeAnalysis:
    @staticmethod
    def get_csv_data(file_path):
        queue_to_time = {}
        last_index = 0
        base_time = None
        with open(
            file_path,
            newline="",
        ) as csvfile:
            csv_reader = csv.DictReader(csvfile)
            for row in csv_reader:
                relative_time = None
                queue_index = None
                for key, val in row.items():
                    if "unix_time" in key or "relative_time" in key:
                        relative_time = int(val)
                        if "unix_time" in key:
                            if not base_time:
                                base_time = relative_time
                                relative_time = 0
                            else:
                                relative_time -= base_time
                    if "paths_total" in key or "corpus_count" in key:
                        queue_index = int(val)
                assert (
                    relative_time is not None and queue_index is not None
                ), "invalid row"
                if queue_index > last_index:
                    last_index = queue_index
                    queue_to_time[queue_index] = relative_time
        return queue_to_time

    @staticmethod
    def obtain(WORK_DIR, FUZZER, TIME_RANGE, INTERVAL):
        assert os.path.exists(WORK_DIR), f"{WORK_DIR} not exists"
        TIME_RANGE = int(TIME_RANGE)
        INTERVAL = int(INTERVAL)
        WORK_DIR_AFLSHOWMAP = os.path.join(WORK_DIR, "aflshowmap")
        # check if images exist
        TARGETS = set()
        for ar_path in utility.get_workdir_paths(WORK_DIR):
            assert os.path.exists(
                os.path.join(ar_path, "target_args")
            ), f"target_args not found in {ar_path}"
            fuzzer, target, repeat = utility.parse_path_by(ar_path)
            TARGETS.add(target)
        Builder.build_imgs(FUZZERS=[FUZZER], TARGETS=list(TARGETS))
        cpu_allocator = CPUAllocator()
        for ar_path in utility.get_workdir_paths(WORK_DIR):
            fuzzer, target, repeat = utility.parse_path_by(ar_path)
            edges_path = os.path.join(WORK_DIR_AFLSHOWMAP, fuzzer, target, repeat)
            os.makedirs(edges_path, exist_ok=True)
            queue_path = utility.search_folder(ar_path, "queue")
            assert queue_path, f"IMPOSSIBLE! queue not found in {ar_path}"
            if len(os.listdir(edges_path)) == sum(
                [
                    1
                    for _ in os.listdir(queue_path)
                    if os.path.isfile(os.path.join(queue_path, _))
                ]
            ):
                continue
            cpu_id = cpu_allocator.get_free_cpu()
            container_id = utility.get_cmd_res(
                f"""
            docker run \
            -itd \
            --rm \
            --volume={ar_path}:/shared \
            --volume={edges_path}:/aflshowmap \
            --cap-add=SYS_PTRACE \
            --security-opt seccomp=unconfined \
            --cpuset-cpus="{cpu_id}" \
            --network=none \
            "{FUZZER}/{target}" \
            -c '${{SRC}}/edges_by_aflshowmap.sh'
                    """
            ).strip()
            cpu_allocator.append(container_id, cpu_id)
        cpu_allocator.wait_for_done()
        edge_over_time_info = {}
        edge_over_time_path = os.path.join(WORK_DIR_AFLSHOWMAP, "edge_over_time.log")
        if os.path.exists(edge_over_time_path):
            with open(edge_over_time_path, "r", encoding="utf-8") as f:
                edge_over_time_info = json.load(f)
        for ar_path in utility.get_workdir_paths(WORK_DIR):
            fuzzer, target, repeat = utility.parse_path_by(ar_path)
            edge_over_time_info.setdefault(target, [])
            is_done = False
            for item in edge_over_time_info[target]:
                if item["fuzzer"] == fuzzer and item["repeat"] == repeat:
                    is_done = True
                    break
            if is_done:
                continue
            plot_data_path = utility.search_file(ar_path, PLOT_DATA)
            assert plot_data_path, f"{plot_data_path} not exists"
            queue_to_time = EdgeAnalysis.get_csv_data(plot_data_path)
            edge_over_time = {}
            unique_edges = set()
            for i in range(0, TIME_RANGE + INTERVAL, INTERVAL):
                edge_over_time[i] = 0
            for edge_file in sorted(
                os.listdir(os.path.join(WORK_DIR_AFLSHOWMAP, fuzzer, target, repeat))
            ):
                if not edge_file.startswith("id:"):
                    continue
                id = int(edge_file.split(",")[0].lstrip("id:"))
                id += 1
                while id not in queue_to_time and id < max(queue_to_time.keys()):
                    id += 1
                if id not in queue_to_time:
                    continue
                with open(
                    os.path.join(
                        WORK_DIR_AFLSHOWMAP, fuzzer, target, repeat, edge_file
                    ),
                    "r",
                ) as file:
                    for line in file:
                        unique_edges.add(line.split(":")[0].strip())
                for i in range(INTERVAL, TIME_RANGE + INTERVAL, INTERVAL):
                    if i >= queue_to_time[id]:
                        edge_over_time[i] = len(unique_edges)
            edge_over_time_info[target].append(
                {
                    "fuzzer": fuzzer,
                    "repeat": repeat,
                    "edge_over_time": edge_over_time,
                }
            )
            # print(
            #     target,
            #     {
            #         "fuzzer": fuzzer,
            #         "repeat": repeat,
            #         "edge_over_time": edge_over_time,
            #     },
            # )
            # print()
            with open(edge_over_time_path, "w", encoding="utf-8") as f:
                json.dump(edge_over_time_info, f, ensure_ascii=False, indent=4)
        return edge_over_time_info
