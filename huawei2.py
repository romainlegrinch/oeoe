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

@dataclass
class Slice:
    slice_id: int
    bandwidth: float  # in Gbps
    max_delay: int    # in ns
    packets: List[Packet]
    current_packet_idx: int = 0

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
        self.port_bandwidth = port_bandwidth * 1e9  # Convert to bits per second
        self.current_time = 0
        self.slices = []
        self.scheduled_packets = []

    def add_slice(self, slice_id: int, bandwidth: float, max_delay: int, packets_data: List[Tuple[int, int]]):
        packets = [Packet(slice_id, i, arrival_time, size) for i, (arrival_time, size) in enumerate(packets_data)]
        self.slices.append(Slice(slice_id, bandwidth, max_delay, packets))

    def calculate_transmission_time(self, packet_size: int) -> int:
        if self.port_bandwidth == 0:
            raise ValueError("La bande passante du port ne peut pas être zéro.")
        return int((packet_size / self.port_bandwidth) + 0.999999)


    def calculate_packet_priority(self, packet: Packet, slice_obj, current_time: int) -> float:
        time_to_deadline = slice_obj.max_delay - (current_time - packet.arrival_time)
        time_to_deadline = max(1, time_to_deadline)  # Éviter la division par zéro
        transmission_time = self.calculate_transmission_time(packet.size)
        
        if transmission_time == 0:
            return float('inf')  # Assurer une priorité maximale si transmission instantanée
        
        priority = (
            0.7 * (1 / time_to_deadline) +
            0.3 * (packet.size / transmission_time)
        )
        return priority




    def schedule_packets(self):
        ready_packets = []
        ignored_packets = []  # Liste temporaire pour les paquets qui ne peuvent pas être planifiés immédiatement

        while True:
            # Mettre à jour les paquets disponibles dans chaque tranche
            for slice_obj in self.slices:
                current_packet = slice_obj.peek_next_packet()

                # Vérification de l'ordre et de l'urgence (condition 3 et vérification du délai)
                while current_packet and \
                    current_packet.arrival_time <= self.current_time and \
                    current_packet.packet_id == slice_obj.current_packet_idx:
                    current_packet = slice_obj.peek_next_packet()
            
            # Vérifier que la bande passante n'est pas dépassée
                packet_bandwidth = slice_obj.bandwidth
                if current_bandwidth_usage + packet_bandwidth <= self.port_bandwidth:
                    current_bandwidth_usage += packet_bandwidth
                    # Ajouter le paquet au tas de priorité
                    heapq.heappush(ready_packets, (-priority, current_packet.arrival_time, slice_obj.slice_id, current_packet.packet_id, current_packet))
                else:
                    # Mettre en attente ou reporter le paquet
                    ignored_packets.append((priority, current_packet))
                        # Calcul de la priorité du paquet, avec une pondération augmentée pour l'urgence
                    priority = self.calculate_packet_priority(current_packet, slice_obj, self.current_time)

                    # Vérifier si le paquet peut être planifié sans dépasser son délai maximal
                    transmission_time = self.calculate_transmission_time(current_packet.size)
                    if self.current_time - current_packet.arrival_time + transmission_time <= slice_obj.max_delay:
                        # Ajouter le paquet au tas s'il peut être planifié dans le délai imparti
                        heapq.heappush(ready_packets, (-priority, current_packet.arrival_time, current_packet.slice_id, current_packet.packet_id, current_packet))
                        slice_obj.get_next_packet()  # Passer au paquet suivant de cette tranche
                    else:
                        # Si le paquet ne peut pas être planifié maintenant, l'ajouter aux paquets ignorés temporairement
                        ignored_packets.append((priority, current_packet))
                    
                    current_packet = slice_obj.peek_next_packet()

            # Si aucun paquet n'est prêt, avancer `current_time` au prochain temps d'arrivée disponible
            if not ready_packets:
                if all(not slice_obj.has_more_packets() for slice_obj in self.slices):
                    break  # Fin de la planification si tous les paquets ont été traités ou ignorés
                
                # Aller directement au prochain temps d'arrivée de paquet
                next_time = min(
                    (packet.arrival_time for slice_obj in self.slices if (packet := slice_obj.peek_next_packet())),
                    default=self.current_time
                )
                self.current_time = next_time
                continue

            # Planifier le paquet avec la meilleure priorité
            _, _, slice_id, packet_id, packet = heapq.heappop(ready_packets)

            # Calculer le temps de transmission et mettre à jour `current_time`
            transmission_time = self.calculate_transmission_time(packet.size)
            start_time = max(self.current_time, packet.arrival_time)
            end_time = start_time + transmission_time

            # Mettre à jour la séquence de sortie
            packet.processed = True
            self.scheduled_packets.append((end_time, packet.slice_id, packet.packet_id))
            self.current_time = end_time

            # Réessayer les paquets ignorés pour éviter qu'ils soient totalement omis
            ready_packets.extend(
                (-p[0], p[1].arrival_time, p[1].slice_id, p[1].packet_id, p[1]) 
                for p in ignored_packets 
                if self.current_time - p[1].arrival_time + self.calculate_transmission_time(p[1].size) <= self.slices[p[1].slice_id].max_delay
            )
            # Vider la liste des paquets ignorés qui ont été replanifiés
            ignored_packets = [
                (p[0], p[1]) for p in ignored_packets 
                if self.current_time - p[1].arrival_time + self.calculate_transmission_time(p[1].size) > self.slices[p[1].slice_id].max_delay
            ]
            heapq.heapify(ready_packets)  # Réorganiser le tas après ajout des paquets replanifiés




    def verify_constraints(self) -> bool:
        for slice_obj in self.slices:
            last_end_time = 0
            packet_end_times = {pid: end_time for end_time, sid, pid in self.scheduled_packets if sid == slice_obj.slice_id}
            
            for i, packet in enumerate(slice_obj.packets):
                if i not in packet_end_times:
                    return False
                current_end_time = packet_end_times[i]
                if current_end_time < packet.arrival_time or current_end_time < last_end_time:
                    return False
                last_end_time = current_end_time

            total_bits = sum(pkt.size for pkt in slice_obj.packets)
            first_arrival = min(pkt.arrival_time for pkt in slice_obj.packets)
            last_departure = max(end_time for end_time, sid, pid in self.scheduled_packets if sid == slice_obj.slice_id)

            duration = last_departure - first_arrival
            achieved_bandwidth = (total_bits / duration) if duration > 0 else 0
            if achieved_bandwidth < 0.95 * slice_obj.bandwidth:
                return False

        return True

    def get_max_delay(self) -> int:
        max_delay = 0
        for end_time, slice_id, packet_id in self.scheduled_packets:
            packet = next(p for p in self.slices[slice_id].packets if p.packet_id == packet_id)
            delay = end_time - packet.arrival_time
            max_delay = max(max_delay, delay)
        return max_delay

    def get_score(self) -> float:
        if not self.verify_constraints():
            return 0
        max_delay = self.get_max_delay()
        if max_delay == 0:
            return 0
        satisfied_slices = sum(
            all((end_time - packet.arrival_time) <= slice_obj.max_delay 
                for end_time, sid, pid in self.scheduled_packets if sid == slice_obj.slice_id and (packet := slice_obj.packets[pid]))
            for slice_obj in self.slices
        )
        return satisfied_slices / len(self.slices) + 10000 / max_delay

    def print_output(self):
        print(len(self.scheduled_packets))
        print(" ".join(f"{end_time} {slice_id} {packet_id}" for end_time, slice_id, packet_id in self.scheduled_packets))

def main():
    n, port_bw = map(float, input().split())
    scheduler = NetworkSliceScheduler(port_bw)

    for i in range(int(n)):
        m, slice_bw, max_delay = map(float, input().split())
        packets_data = [(int(arrival), int(size)) for arrival, size in zip(*[iter(map(int, input().split()))] * 2)]
        scheduler.add_slice(i, slice_bw, int(max_delay), packets_data)

    scheduler.schedule_packets()
    scheduler.print_output()

if __name__ == "__main__":
    main()
