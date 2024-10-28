from dataclasses import dataclass
from typing import List, Tuple
import heapq

@dataclass
class Packet:
    slice_id: int
    packet_id: int
    arrival_time: int
    size: int
    processed: bool = False
    departure_time: int = 0

@dataclass
class Slice:
    slice_id: int
    bandwidth: float
    max_delay: int
    packets: List[Packet]
    current_packet_idx: int = 0
    last_departure_time: int = 0
    packet_count: int = 0

    def has_more_packets(self) -> bool:
        return self.current_packet_idx < len(self.packets)

    def peek_next_packet(self) -> Packet:
        if self.has_more_packets():
            return self.packets[self.current_packet_idx]
        return None

    def get_next_packet(self) -> Packet:
        if self.has_more_packets():
            packet = self.packets[self.current_packet_idx]
            self.current_packet_idx += 1
            return packet
        return None

class NetworkSliceScheduler:
    def __init__(self, port_bandwidth: float):
        self.port_bandwidth = port_bandwidth * 1e9
        self.current_time = 0
        self.slices = []
        self.scheduled_packets = []
        self.last_departure_time = 0
        self.total_packets = 0

    def add_slice(self, slice_id: int, bandwidth: float, max_delay: int, packets_data: List[Tuple[int, int]]):
        packets = [Packet(slice_id, i, arrival_time, size) for i, (arrival_time, size) in enumerate(packets_data)]
        slice_obj = Slice(slice_id, bandwidth, max_delay, packets)
        slice_obj.packet_count = len(packets)
        self.slices.append(slice_obj)
        self.total_packets += len(packets)

    def calculate_transmission_time(self, packet_size: int) -> int:
        return int((packet_size / self.port_bandwidth) * 1e9)

    def calculate_earliest_start_time(self, packet: Packet, slice_obj: Slice) -> int:
        earliest_start = max(packet.arrival_time, self.last_departure_time)
        if slice_obj.last_departure_time > 0:
            earliest_start = max(earliest_start, slice_obj.last_departure_time)
        return earliest_start

    def calculate_packet_priority(self, packet: Packet, slice_obj: Slice, current_time: int) -> float:
        time_to_deadline = slice_obj.max_delay - (current_time - packet.arrival_time)
        urgency = 1.0 / max(1, time_to_deadline)
        transmission_time = self.calculate_transmission_time(packet.size)
        efficiency = packet.size / transmission_time
        processed_ratio = sum(1 for p in slice_obj.packets if p.processed) / len(slice_obj.packets)
        fairness = 1.0 - processed_ratio
        return 0.6 * urgency + 0.2 * efficiency + 0.2 * fairness

    def can_schedule_packet(self, packet: Packet, slice_obj: Slice, start_time: int) -> bool:
        transmission_time = self.calculate_transmission_time(packet.size)
        end_time = start_time + transmission_time
        if end_time - packet.arrival_time > slice_obj.max_delay * 1.1:
            return False
        total_bits = packet.size
        first_arrival = packet.arrival_time
        for p in slice_obj.packets:
            if p.processed:
                total_bits += p.size
                first_arrival = min(first_arrival, p.arrival_time)
        duration = end_time - first_arrival
        if duration > 0:
            achieved_bandwidth = (total_bits * 1e9) / duration
            target_bandwidth = slice_obj.bandwidth * 1e9 * 0.95
            if achieved_bandwidth < target_bandwidth * 0.9:
                return False
        return True


    def schedule_packets(self):
        ready_packets = []
        delayed_packets = []

        while True:
            for slice_obj in self.slices:
                while slice_obj.has_more_packets():
                    current_packet = slice_obj.peek_next_packet()
                    if current_packet.arrival_time > self.current_time:
                        break
                    start_time = self.calculate_earliest_start_time(current_packet, slice_obj)
                    if self.can_schedule_packet(current_packet, slice_obj, start_time):
                        priority = self.calculate_packet_priority(current_packet, slice_obj, self.current_time)
                        # Do not push the slice_obj itself
                        heapq.heappush(ready_packets, (-priority, current_packet.arrival_time, slice_obj.slice_id, current_packet.packet_id, current_packet))
                    else:
                        delayed_packets.append((slice_obj, current_packet))
                    slice_obj.get_next_packet()

            remaining_delayed = []
            for slice_obj, packet in delayed_packets:
                start_time = self.calculate_earliest_start_time(packet, slice_obj)
                if self.can_schedule_packet(packet, slice_obj, start_time):
                    priority = self.calculate_packet_priority(packet, slice_obj, self.current_time)
                    heapq.heappush(ready_packets, (-priority, packet.arrival_time, slice_obj.slice_id, packet.packet_id, packet))
                else:
                    remaining_delayed.append((slice_obj, packet))
            delayed_packets = remaining_delayed

            if not ready_packets:
                if not delayed_packets and all(not slice_obj.has_more_packets() for slice_obj in self.slices):
                    break
                next_time = float('inf')
                for slice_obj in self.slices:
                    if slice_obj.has_more_packets():
                        next_time = min(next_time, slice_obj.peek_next_packet().arrival_time)
                if next_time == float('inf'):
                    self.current_time += 1
                else:
                    self.current_time = next_time
                continue

            _, _, slice_id, packet_id, packet = heapq.heappop(ready_packets)
            transmission_time = self.calculate_transmission_time(packet.size)
            start_time = max(self.current_time, packet.arrival_time)
            end_time = start_time + transmission_time
            packet.processed = True
            packet.departure_time = end_time
            self.slices[slice_id].last_departure_time = end_time
            self.last_departure_time = end_time
            self.current_time = end_time
            self.scheduled_packets.append((end_time, packet.slice_id, packet.packet_id))
    def get_score(self) -> float:
        if len(self.scheduled_packets) < self.total_packets:
            return 0
        max_delay = 0
        satisfied_slices = 0
        for slice_obj in self.slices:
            slice_max_delay = 0
            for packet in slice_obj.packets:
                if not packet.processed:
                    return 0
                delay = packet.departure_time - packet.arrival_time
                slice_max_delay = max(slice_max_delay, delay)
                max_delay = max(max_delay, delay)
            if slice_max_delay <= slice_obj.max_delay:
                satisfied_slices += 1
        return satisfied_slices / len(self.slices) + 10000 / max_delay

    def print_output(self):
        print(len(self.scheduled_packets))
        output_line = " ".join(f"{time} {slice_id} {packet_id}" for time, slice_id, packet_id in sorted(self.scheduled_packets))
        print(output_line)

def main():
    n, port_bw = map(float, input().split())
    n = int(n)
    scheduler = NetworkSliceScheduler(port_bw)
    for i in range(n):
        m, slice_bw, max_delay = map(float, input().split())
        m = int(m)
        packets_data = [(int(arrival), int(size)) for arrival, size in zip(*[iter(map(int, input().split()))] * 2)]
        scheduler.add_slice(i, slice_bw, int(max_delay), packets_data)
    scheduler.schedule_packets()
    scheduler.print_output()

if __name__ == "__main__":
    main()