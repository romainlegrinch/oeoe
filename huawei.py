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
        self.port_bandwidth = port_bandwidth * 1e9
        self.current_time = 0
        self.slices = []
        self.scheduled_packets = []
        
    def add_slice(self, slice_id: int, bandwidth: float, max_delay: int, packets_data: List[Tuple[int, int]]):
        packets = []
        for i, (arrival_time, size) in enumerate(packets_data):
            packets.append(Packet(slice_id, i, arrival_time, size))
        self.slices.append(Slice(slice_id, bandwidth, max_delay, packets))
    def calculate_packet_priority(self, packet: Packet, slice_obj, current_time: int) -> float:
        # Calculer le temps restant avant la deadline
        time_to_deadline = slice_obj.max_delay - (current_time - packet.arrival_time)
        
        # Calculer le temps de transmission nécessaire
        transmission_time = self.calculate_transmission_time(packet.size)
        
        # Calculer la densité (valeur/temps) du paquet
        density = packet.size / transmission_time
        
        # Calculer le ratio de bande passante utilisée pour cette slice
        slice_usage = self.calculate_slice_bandwidth_usage(slice_obj)
        
        # Combiner les facteurs avec des poids
        priority = (
            0.4 * (1 / max(1, time_to_deadline)) +  # Urgence
            0.3 * density +                         # Efficacité
            0.3 * (1 - slice_usage)                # Équité entre slices
        )
        
        return priority

    def calculate_transmission_time(self, packet_size: int) -> int:
        # Convert to exact nanoseconds
        return int((packet_size / self.port_bandwidth) * 1e9)
    def calculate_slice_bandwidth_usage(self, slice_obj) -> float:
        total_bits = 0
        total_time = 0
        
        for packet in slice_obj.packets:
            if packet.processed:
                total_bits += packet.size
                for end_time, sid, pid in self.scheduled_packets:
                    if sid == slice_obj.slice_id and pid == packet.packet_id:
                        total_time = max(total_time, end_time - packet.arrival_time)
        
        if total_time == 0:
            return 0
            
        current_bandwidth = (total_bits * 1e9) / total_time
        target_bandwidth = slice_obj.bandwidth * 1e9
        
        return min(1.0, current_bandwidth / target_bandwidth)
    def schedule_packets(self):
        ready_packets = []
        ignored_packets = []  # Liste pour les paquets temporairement ignorés

        while True:
            # Mise à jour des paquets disponibles dans chaque tranche
            for slice_obj in self.slices:
                current_packet = slice_obj.peek_next_packet()

                # S'assurer que le paquet est bien le suivant dans l'ordre d'arrivée
                while current_packet and \
                    current_packet.arrival_time <= self.current_time and \
                    current_packet.packet_id == slice_obj.current_packet_idx:
                    
                    # Calcul de la priorité avec un poids pour l'urgence
                    priority = self.calculate_packet_priority(current_packet, slice_obj, self.current_time)

                    # Vérification du respect du délai et de la condition d'arrivée
                    transmission_time = self.calculate_transmission_time(current_packet.size)
                    if self.current_time >= current_packet.arrival_time and \
                    (self.current_time - current_packet.arrival_time + transmission_time) <= slice_obj.max_delay:
                        # Ajouter au tas si planifiable dans le délai imparti
                        heapq.heappush(ready_packets, (-priority, current_packet.arrival_time, current_packet.slice_id, current_packet.packet_id, current_packet))
                        slice_obj.get_next_packet()  # Passer au paquet suivant de cette tranche
                    else:
                        # Ajouter aux paquets ignorés pour une tentative ultérieure
                        ignored_packets.append((priority, current_packet))
                    
                    current_packet = slice_obj.peek_next_packet()

            # Si aucun paquet n'est prêt, avancer `current_time` au prochain temps d'arrivée disponible
            if not ready_packets:
                if all(not slice_obj.has_more_packets() for slice_obj in self.slices):
                    break  # Fin de la planification si tous les paquets ont été traités ou ignorés
                
                # Aller au prochain temps d'arrivée d'un paquet
                next_time = min(
                    (packet.arrival_time for slice_obj in self.slices if (packet := slice_obj.peek_next_packet())),
                    default=self.current_time
                )
                self.current_time = next_time
                continue

            # Planifier le paquet avec la meilleure priorité
            _, _, slice_id, packet_id, packet = heapq.heappop(ready_packets)

            # Calculer le temps de transmission et vérifier la condition de départ après l'arrivée
            transmission_time = self.calculate_transmission_time(packet.size)
            start_time = max(self.current_time, packet.arrival_time)  # Départ ne peut être avant l'arrivée
            end_time = start_time + transmission_time

            # Enregistrer le paquet dans la séquence de sortie
            packet.processed = True
            self.scheduled_packets.append((end_time, packet.slice_id, packet.packet_id))
            self.current_time = end_time

            # Réévaluer les paquets ignorés pour vérifier s'ils sont maintenant planifiables
            ready_packets.extend(
                (-p[0], p[1].arrival_time, p[1].slice_id, p[1].packet_id, p[1]) 
                for p in ignored_packets 
                if self.current_time >= p[1].arrival_time and 
                (self.current_time - p[1].arrival_time + self.calculate_transmission_time(p[1].size)) <= self.slices[p[1].slice_id].max_delay
            )
            # Mettre à jour la liste des ignorés pour ceux encore hors délai
            ignored_packets = [
                (p[0], p[1]) for p in ignored_packets 
                if not (self.current_time >= p[1].arrival_time and 
                        (self.current_time - p[1].arrival_time + self.calculate_transmission_time(p[1].size)) <= self.slices[p[1].slice_id].max_delay)
            ]
            heapq.heapify(ready_packets)  # Réorganiser le tas après ajout des paquets replanifiés


    def verify_constraints(self) -> bool:
        # Verify packet ordering within slices
        for slice_obj in self.slices:
            last_end_time = 0
            packet_times = {}
            
            for end_time, slice_id, packet_id in self.scheduled_packets:
                if slice_id == slice_obj.slice_id:
                    packet_times[packet_id] = end_time
            
            for i in range(len(slice_obj.packets)):
                if i not in packet_times:
                    return False
                current_end_time = packet_times[i]
                if current_end_time < slice_obj.packets[i].arrival_time:
                    return False
                if current_end_time < last_end_time:
                    return False
                last_end_time = current_end_time

        # Verify bandwidth constraints
        for slice_obj in self.slices:
            total_bits = 0
            first_arrival = float('inf')
            last_departure = 0
            
            for packet in slice_obj.packets:
                total_bits += packet.size
                first_arrival = min(first_arrival, packet.arrival_time)
            
            for end_time, slice_id, packet_id in self.scheduled_packets:
                if slice_id == slice_obj.slice_id:
                    last_departure = max(last_departure, end_time)
            
            duration = last_departure - first_arrival
            if duration > 0:
                achieved_bandwidth = (total_bits * 1e9) / (duration)  # convert to bps
                if achieved_bandwidth < 0.95 * slice_obj.bandwidth * 1e9:
                    return False

        return True

    def get_max_delay(self) -> int:
        max_delay = 0
        for slice_obj in self.slices:
            for packet in slice_obj.packets:
                for end_time, slice_id, packet_id in self.scheduled_packets:
                    if slice_id == slice_obj.slice_id and packet_id == packet.packet_id:
                        delay = end_time - packet.arrival_time
                        max_delay = max(max_delay, delay)
        return max_delay

    def get_score(self) -> float:
        if not self.verify_constraints():
            return 0
            
        max_delay = self.get_max_delay()
        if max_delay == 0:
            return 0
            
        satisfied_slices = 0
        for slice_obj in self.slices:
            slice_max_delay = 0
            for packet in slice_obj.packets:
                for end_time, slice_id, packet_id in self.scheduled_packets:
                    if slice_id == slice_obj.slice_id and packet_id == packet.packet_id:
                        delay = end_time - packet.arrival_time
                        slice_max_delay = max(slice_max_delay, delay)
            if slice_max_delay <= slice_obj.max_delay:
                satisfied_slices += 1
                
        return satisfied_slices / len(self.slices) + 10000 / max_delay

    def print_output(self):
        print(len(self.scheduled_packets))
        output_line = " ".join(f"{time} {slice_id} {packet_id}" 
                             for time, slice_id, packet_id in sorted(self.scheduled_packets))
        print(output_line)

def main():
    # Read input
    n, port_bw = map(float, input().split())
    n = int(n)
    
    scheduler = NetworkSliceScheduler(port_bw)
    
    # Read slice information
    for i in range(n):
        m, slice_bw, max_delay = map(float, input().split())
        m = int(m)
        packets_data = []
        
        # Read packet information
        packet_info = list(map(int, input().split()))
        for j in range(0, len(packet_info), 2):
            arrival_time = packet_info[j]
            packet_size = packet_info[j + 1]
            packets_data.append((arrival_time, packet_size))
            
        scheduler.add_slice(i, slice_bw, int(max_delay), packets_data)
    
    scheduler.schedule_packets()
    scheduler.print_output()

if __name__ == "__main__":
    main()