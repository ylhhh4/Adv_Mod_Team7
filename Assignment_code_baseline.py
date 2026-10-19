# =============================================================================
# PARAMETERS
# =============================================================================

SIMULATION_STEPS = 365  # STEP (DAYS)

CRATE_TYPE_NAMES = ['TYPE_1', 'TYPE_2', 'TYPE_3', 'TYPE_4']
UL_SIZE = 200 # RTI
TRUCK_CAPACITY = 33 # UL

PRO_REORDER_POINT = 5000 # RTI
PRO_REORDER_QTY = 1 * TRUCK_CAPACITY # UL
PRO_ORDER_LT = 1 # STEP
WASHING_REQUIREMENT_RATE = 0.50 # %

RDC_DAILY_DEMAND_MEAN = 7000 # RTI
RDC_DAILY_DEMAND_STD = 1000 # RTI

RPOS_DISPLAY_TIME = {'big': 1, 'medium': 1, 'small': 2} # STEPS

RTI_BREAKAGE_RATE = 0.05 # %
POOL_SCREENING_CAPACITY = 20 # UL
POOL_PROCESSING_TIME = 1 # STEP

POOLER = "POOL_1"
PRODUCERS = [
    {"id": "PRO_1", "product": "Orange", "makes_dirty": False, "compatible_crates": ['TYPE_1', 'TYPE_3']},
    {"id": "PRO_2", "product": "Lemon", "makes_dirty": False, "compatible_crates": ['TYPE_2', 'TYPE_4']},
    {"id": "PRO_3", "product": "Apple", "makes_dirty": False, "compatible_crates": ['TYPE_3', 'TYPE_4']},
    {"id": "PRO_4", "product": "Banana", "makes_dirty": True, "compatible_crates": ['TYPE_2', 'TYPE_3']},
    {"id": "PRO_5", "product": "Peach", "makes_dirty": True, "compatible_crates": ['TYPE_1', 'TYPE_3']},
    {"id": "PRO_6", "product": "Plum", "makes_dirty": True, "compatible_crates": ['TYPE_2']},
    {"id": "PRO_7", "product": "Strawberry", "makes_dirty": True, "compatible_crates": ['TYPE_1', 'TYPE_4']}
]
RDC = "RDC_1"
N_RPOS_BIG = 5
N_RPOS_MEDIUM = 5
N_RPOS_SMALL = 10
N_RPOS = N_RPOS_BIG + N_RPOS_MEDIUM + N_RPOS_SMALL

INIT_POOL_WASHED_UL = 100 # UL
INIT_POOL_UNWASHED_UL = 100 # UL
INIT_PRO_UL = 50 # UL
INIT_RDC_UL = 15 # UL
INIT_RPOS_RTI = 260 # RTI


# =============================================================================
# IMPORTS
# =============================================================================

import os
import mesa
import uuid
import copy
import random
import pandas as pd
from enum import Enum
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, field


# =============================================================================
# DATA CLASSES & ENUMS
# =============================================================================

_crate_type_members = {name: name.lower() for name in CRATE_TYPE_NAMES}
CrateType = Enum('CrateType', _crate_type_members)
ALL_CRATE_TYPES = list(CrateType)

@dataclass(frozen=True)
class Product:
    name: str
    makes_dirty: bool
    compatible_crates: List[CrateType]

@dataclass
class OrderLine:
    issuer: str
    supplier: str
    order_id: str
    crate_type: CrateType
    quantity: int
    uom: str
    lead_time: int
    creation_step: int
    product: Optional[Product] = None
    needs_washed: Optional[bool] = None

@dataclass
class UnitLoad:
    id: str = field(default_factory=lambda: str(uuid.uuid4())) #generates random universally unique identifier
    crate_type: CrateType = field(default_factory=lambda: list(CrateType)[0]) #prende la prima tipologia di cassette nella lista CrateType.TYPE_1  
    rtis: List['RTI_Agent'] = field(default_factory=list)
    
    def add_rti(self, rti: 'RTI_Agent'):
        self.rtis.append(rti)
        
        
class LocationType(Enum):
    POOL = "pool"
    PRO = "pro"
    R_DC = "r_dc"
    R_POS = "r_pos"
    TRANSPORT = "transport"


# =============================================================================
# AGENT CLASSES
# =============================================================================

class RTI_Agent(mesa.Agent):
    def __init__(self, model, crate_type: CrateType = None, washed: bool = True, 
                 location: LocationType = LocationType.POOL, is_filled: bool = False, 
                 product: Optional[Product] = None):
        super().__init__(model)
        
        if crate_type is None:
            crate_type = list(CrateType)[0]
        
        self.rti_id = str(uuid.uuid4())
        self.crate_type = crate_type
        self.product = product
        self.is_filled = is_filled
        self.under_processing = False
        self.washed = washed
        self.location = location
        self.arrival_time_at_node = 0
        self.detention_time = 0
        self.broken = False
        self.dirty = False
        self.goes_to_stock_after_processing = True
        self.transported_this_step = False
        
class Pooler_Agent(mesa.Agent):
    def __init__(self, model, pool_id: str):
        super().__init__(model)
        self.pool_id = pool_id
        
        self.washed_stock_pool = {
            ct: [UnitLoad(crate_type=ct, rtis=[RTI_Agent(self.model, ct, washed=True, location=LocationType.POOL) for _ in range(UL_SIZE)]) for _ in range(INIT_POOL_WASHED_UL)]
            for ct in CrateType
        }
        
        self.unwashed_stock_pool = {
            ct: [UnitLoad(crate_type=ct, rtis=[RTI_Agent(self.model, ct, washed=False, location=LocationType.POOL) for _ in range(UL_SIZE)]) for _ in range(INIT_POOL_UNWASHED_UL)]
            for ct in CrateType
        }
        
        self.processing_buffer = []
        self.processing_times = {}      
        self.processing_lead_time = POOL_PROCESSING_TIME
        self.order_book: List[OrderLine] = []
        
    def receive_orders(self, order: OrderLine):
        self.order_book.append(order)
          
    def extract_uls(self, crate_type: CrateType, needs_washed: Optional[bool], quantity_uls: int) -> List[UnitLoad]:      
        if needs_washed is True:
            primary_stock = self.washed_stock_pool[crate_type]
            secondary_stock = []
        else:
            primary_stock = self.unwashed_stock_pool[crate_type]
            secondary_stock = self.washed_stock_pool[crate_type]
            
        primary_available = len(primary_stock)
        secondary_available = len(secondary_stock)
        total_available = primary_available + secondary_available
        
        selected_uls = []
        
        if total_available >= quantity_uls:
            if primary_available >= quantity_uls:
                selected_uls = random.sample(primary_stock, quantity_uls)
                for ul in selected_uls:
                    primary_stock.remove(ul)
            else:
                selected_primary = list(primary_stock)
                primary_stock.clear()
                
                needed = quantity_uls - primary_available
                selected_secondary = random.sample(secondary_stock, needed)
                for ul in selected_secondary:
                    secondary_stock.remove(ul)
                    
                selected_uls = selected_primary + selected_secondary
                
        else:
            selected_uls = list(primary_stock) + list(secondary_stock)
            primary_stock.clear()
            if secondary_stock:
                secondary_stock.clear()
                            
        return selected_uls
        
    def fulfill_orders(self):
        due_orders = [o for o in self.order_book if self.model.steps >= (o.creation_step + o.lead_time)]
        due_orders.sort(key=lambda x: x.creation_step)
        
        for order in due_orders:
            extracted_uls = self.extract_uls(order.crate_type, order.needs_washed, order.quantity)
            extracted_qty_uls = len(extracted_uls)
            
            if extracted_qty_uls > 0:
                for ul in extracted_uls:
                    for rti in ul.rtis:
                        rti.location = LocationType.TRANSPORT
                        rti.transported_this_step = True
                        rti.detention_time = 0
                
                target_pro = self.model.producers_by_id[order.issuer]
                target_pro.receive_uls(extracted_uls)
                
                self.model.daily_log['movements']['pool_to_pro'][order.issuer][order.crate_type] += extracted_qty_uls * UL_SIZE
            
            shortage_uls = order.quantity - extracted_qty_uls
            if shortage_uls > 0:
                order.quantity = shortage_uls
            else:
                self.order_book.remove(order)            

    def receive_uls(self, uls: List[UnitLoad]):
        current_step = self.model.steps
        
        for ul in uls:
            
            for rti in ul.rtis:                               
                self.evaluate_rti_condition(rti, current_step)
                rti.location = LocationType.POOL
            
        self.screen_uls(uls, current_step)
        
    def screen_uls(self, uls: List[UnitLoad], current_step: int):

        num_uls_to_screen = min(len(uls), POOL_SCREENING_CAPACITY)
        uls_to_screen = random.sample(uls, num_uls_to_screen) if num_uls_to_screen > 0 else []
        uls_to_bypass = [ul for ul in uls if ul not in uls_to_screen]
                
        for ul in uls_to_screen:
            self.processing_buffer.append(ul)
            self.processing_times[ul.id] = current_step
            for rti in ul.rtis:
                rti.under_processing = True
        
        for ul in uls_to_bypass:
            self.unwashed_stock_pool[ul.crate_type].append(ul)
            
    def process_uls(self):
        current_time = self.model.steps
        
        ready_uls = [ul for ul in self.processing_buffer 
                     if current_time - self.processing_times.get(ul.id, current_time) >= self.processing_lead_time]
        
        for ul in ready_uls:
            for rti in ul.rtis:
                self.process_rti(rti)
                rti.under_processing = False
                rti.goes_to_stock_after_processing = True

            self.washed_stock_pool[ul.crate_type].append(ul)
            self.processing_buffer.remove(ul)
            del self.processing_times[ul.id]
    
    def process_rti(self, rti: RTI_Agent) -> Optional[RTI_Agent]:
        if rti.broken:
                rti.broken = False
                rti.dirty = True
        
        rti.dirty = False
        rti.washed = True
        return rti
                
    def evaluate_rti_condition(self, rti: RTI_Agent, current_step: int):
        
        if random.random() < RTI_BREAKAGE_RATE:
            rti.broken = True
            
        if not rti.dirty:
            if rti.product is not None and rti.product.makes_dirty:
                rti.dirty = True
        rti.product = None
    
    def step(self):
        self.process_uls()
        self.fulfill_orders()
        
        for uls in self.washed_stock_pool.values():
            for ul in uls:
                for rti in ul.rtis:
                    rti.detention_time += 1
                    
        for uls in self.unwashed_stock_pool.values():
            for ul in uls:
                for rti in ul.rtis:
                    rti.detention_time += 1

        for ul in self.processing_buffer:
            for rti in ul.rtis:
                rti.detention_time += 1

class Producer_Agent(mesa.Agent):
    def __init__(self, model, producer_id: str, product: Product):
        super().__init__(model)
        self.producer_id = producer_id
        self.product = product
        self.compatible_crates = set(self.product.compatible_crates)
        self.order_book: List[OrderLine] = []
        self.on_order_from_pool = {ct: 0 for ct in CrateType}
        
        self.forward_stock_pro = {
            ct: [RTI_Agent(self.model, ct, washed=False, location=LocationType.PRO, is_filled=False) for _ in range(INIT_PRO_UL * UL_SIZE)] if ct in self.compatible_crates else []
            for ct in CrateType
        }
                                
    def generate_orders(self):
        for ct in self.compatible_crates:
            physical_stock = len(self.forward_stock_pro[ct])
            transit_stock = self.on_order_from_pool[ct]
            backordered_stock = sum(o.quantity for o in self.order_book if o.crate_type == ct)
            
            inventory_position = physical_stock + transit_stock - backordered_stock
            
            if inventory_position <= PRO_REORDER_POINT:
                rtis_ordered = PRO_REORDER_QTY * UL_SIZE
                
                self.on_order_from_pool[ct] += rtis_ordered
                
                requires_washing_this_time = random.random() < WASHING_REQUIREMENT_RATE
                
                order = OrderLine(
                    issuer=self.producer_id,
                    supplier=self.model.pool_agent.pool_id,
                    order_id=str(uuid.uuid4()),
                    crate_type=ct,
                    quantity=PRO_REORDER_QTY,
                    uom='UL',
                    lead_time=PRO_ORDER_LT,
                    creation_step=self.model.steps,
                    product=None,
                    needs_washed=requires_washing_this_time
                )
                self.model.pool_agent.receive_orders(order)
                self.model.all_orders.append(copy.copy(order))
    
    def receive_uls(self, uls: List[UnitLoad]):
        if not uls: return
                
        for ul in uls:
            for rti in ul.rtis:
                self.on_order_from_pool[rti.crate_type] = max(0, self.on_order_from_pool[rti.crate_type] - 1)
                rti.location = LocationType.PRO
                rti.washed = False
                self.forward_stock_pro[rti.crate_type].append(rti)
        
    def receive_orders(self, order: OrderLine):
        self.order_book.append(order)

    def extract_rtis(self, quantity: int, crate_type: CrateType) -> List[RTI_Agent]:
        available = self.forward_stock_pro[crate_type]
        available_qty = len(available)
        
        if available_qty == 0:
            return []
        
        qty_to_sample = min(quantity, available_qty)
        rtis_to_send = random.sample(available, qty_to_sample)
        
        for rti in rtis_to_send:
            available.remove(rti)
        return rtis_to_send
    
    def fulfill_orders(self):
        due_orders = [o for o in self.order_book if self.model.steps >= (o.creation_step + o.lead_time)]
        due_orders.sort(key=lambda x: x.creation_step)
        
        for order in due_orders:
            extracted_rtis = self.extract_rtis(order.quantity, order.crate_type)
            extracted_qty = len(extracted_rtis)
            
            if extracted_qty > 0:
                for rti in extracted_rtis:
                    rti.is_filled = True
                    rti.product = order.product
                    rti.location = LocationType.TRANSPORT
                    rti.transported_this_step = True
                    rti.detention_time = 0

                self.model.rdc_agent.receive_rtis(extracted_rtis)
                self.model.daily_log['movements']['pro_to_rdc'][self.producer_id][order.crate_type] += extracted_qty
            
            shortage = order.quantity - extracted_qty
            if shortage > 0:
                order.quantity = shortage
            else:
                self.order_book.remove(order)

    def step(self):
        self.fulfill_orders()
        self.generate_orders()
                
        for rti_list in self.forward_stock_pro.values():
            for rti in rti_list:
                rti.detention_time += 1
        

class RDC_Agent(mesa.Agent):
    def __init__(self, model, rdc_id: str):
        super().__init__(model)
        self.rdc_id = rdc_id
        self.forward_rtis_received_this_step = []
        
        comp_prods = {ct: [p for p in self.model.products if ct in p.compatible_crates] for ct in CrateType}
        self.reverse_stock_rdc = {
            ct: [
                UnitLoad(
                    crate_type=ct, 
                    rtis=[
                        RTI_Agent(
                            self.model, ct, washed=False, location=LocationType.R_DC, is_filled=False, 
                            product=random.choice(comp_prods[ct]) if comp_prods[ct] else None
                        ) for _ in range(UL_SIZE)
                    ]
                ) for _ in range(INIT_RDC_UL)
            ]
            for ct in CrateType
        }
        
    def generate_orders(self):
        total_demand = max(0, int(random.gauss(RDC_DAILY_DEMAND_MEAN, RDC_DAILY_DEMAND_STD)))
        if total_demand == 0:
            return

        remaining_demand = total_demand
        while remaining_demand > 0:
            qty_to_request = min(remaining_demand, random.randint(500, 1000))
            
            potential_remainder = remaining_demand - qty_to_request
            if 0 < potential_remainder < 100:
                qty_to_request += potential_remainder

            remaining_demand -= qty_to_request

            target_producer = random.choice(self.model.producers)
            product = target_producer.product
            crate_type = random.choice(product.compatible_crates)
            lead_time = random.randint(1, 3)

            order = OrderLine(
                issuer=self.rdc_id,
                supplier=target_producer.producer_id,
                order_id=str(uuid.uuid4()),
                product=product,
                crate_type=crate_type,
                quantity=qty_to_request,
                uom='RTI',
                lead_time=lead_time,
                creation_step=self.model.steps
            )
            
            self.model.all_orders.append(copy.copy(order))

            target_producer.receive_orders(order)
        
    def receive_rtis(self, rtis: List[RTI_Agent]):
        for rti in rtis:
            rti.location = LocationType.R_DC
            self.forward_rtis_received_this_step.append(rti)
    
    def extract_rtis(self) -> List[RTI_Agent]:
        rtis = self.forward_rtis_received_this_step.copy()
        self.forward_rtis_received_this_step.clear()
        return rtis
    
    def allocate_rtis(self, rtis: List[RTI_Agent]) -> Dict:
        if not rtis: return {}
        clusters = {'small': [], 'medium': [], 'big': []}
        
        for rpos in self.model.r_pos_agents: clusters[rpos.size].append(rpos)
        
        weights = {'small': 1, 'medium': 2, 'big': 3}
        total_weight = sum(weights[sz] * len(lst) for sz, lst in clusters.items())
        
        allocation = {rpos: [] for rpos in self.model.r_pos_agents}
        rtis_remaining = rtis.copy()
        
        for size in ['small', 'medium', 'big']:
            pos_list = clusters[size]
            if not pos_list: continue
            cluster_w = weights[size] * len(pos_list)
            qty_cluster = min(round(len(rtis) * cluster_w / total_weight), len(rtis_remaining))
            
            cluster_rtis = rtis_remaining[:qty_cluster]
            rtis_remaining = rtis_remaining[qty_cluster:]
            
            base_pos = len(cluster_rtis) // len(pos_list)
            rem = len(cluster_rtis) % len(pos_list)
            idx = 0
            for i, rpos in enumerate(pos_list):
                count = base_pos + (1 if i < rem else 0)
                allocation[rpos] = cluster_rtis[idx:idx+count]
                idx += count
        if rtis_remaining: allocation[self.model.r_pos_agents[0]].extend(rtis_remaining)
        return allocation
    
    def dispatch_rtis(self):
        rtis = self.extract_rtis()
        if not rtis: return
        
        for rti in rtis:
            self.model.daily_log['movements']['rdc_to_pos'][rti.crate_type] += 1
        
        random.shuffle(rtis)
        allocation = self.allocate_rtis(rtis)
        
        for rpos, rti_list in allocation.items():
            for rti in rti_list:
                rti.location = LocationType.TRANSPORT
                rti.transported_this_step = True
            rpos.receive_rtis(rti_list)
    
    def receive_uls(self, uls: List[UnitLoad]):
        for ul in uls:            
            for rti in ul.rtis:
                rti.location = LocationType.R_DC
                
            self.reverse_stock_rdc[ul.crate_type].append(ul)
                
    def extract_uls(self):
        all_available_uls = [ul for uls in self.reverse_stock_rdc.values() for ul in uls]
        num_trucks = len(all_available_uls) // TRUCK_CAPACITY
        
        if num_trucks == 0:
            return
            
        random.shuffle(all_available_uls)
        uls_to_ship = all_available_uls[:num_trucks * TRUCK_CAPACITY]
        
        for ul in uls_to_ship:
            self.reverse_stock_rdc[ul.crate_type].remove(ul)
            for rti in ul.rtis:
                rti.location = LocationType.TRANSPORT
                rti.transported_this_step = True
                rti.detention_time = 0
            self.model.daily_log['movements']['rdc_to_pool'][ul.crate_type] += len(ul.rtis)
            
        self.model.pool_agent.receive_uls(uls_to_ship)
            
    def step(self):
        for uls in self.reverse_stock_rdc.values():
            for ul in uls:
                for rti in ul.rtis:
                    rti.detention_time += 1

class RPOS_Agent(mesa.Agent):
    def __init__(self, model, size: str):
        super().__init__(model)
        self.size = size
        self.display_time = RPOS_DISPLAY_TIME[size]
        self.reverse_stock_rpos = {ct: [] for ct in CrateType}
        
        self.displayed_rtis_rpos = [
            RTI_Agent(self.model, ct, washed=False, location=LocationType.R_POS, is_filled=True)
            for ct in CrateType for _ in range(INIT_RPOS_RTI)
        ]
    
    def receive_rtis(self, rtis: List[RTI_Agent]):
        current_step = self.model.steps
        for rti in rtis:
            rti.arrival_time_at_node = current_step
            rti.location = LocationType.R_POS
            self.displayed_rtis_rpos.append(rti)
    
    def process_sales(self):
        current_step = self.model.steps
        ready = [rti for rti in self.displayed_rtis_rpos 
                 if current_step - rti.arrival_time_at_node >= self.display_time]
        
        for rti in ready:
            self.displayed_rtis_rpos.remove(rti)
            rti.is_filled = False
            self.reverse_stock_rpos[rti.crate_type].append(rti)
            
    def extract_rtis(self):
        uls_to_dispatch = []
        
        for ct in CrateType:
            available_rtis = self.reverse_stock_rpos[ct]
            random.shuffle(available_rtis)
            num_full_uls = len(available_rtis) // UL_SIZE
            
            for _ in range(num_full_uls):
                ul = UnitLoad()
                ul.crate_type = ct
                
                rtis_for_ul = available_rtis[:UL_SIZE]
                self.reverse_stock_rpos[ct] = available_rtis[UL_SIZE:]
                available_rtis = self.reverse_stock_rpos[ct]
                
                for rti in rtis_for_ul:
                    rti.location = LocationType.TRANSPORT
                    rti.transported_this_step = True
                    rti.detention_time = 0
                    ul.add_rti(rti)
                
                uls_to_dispatch.append(ul)
                
        if uls_to_dispatch:
            for ul in uls_to_dispatch:
                self.model.daily_log['movements']['pos_to_rdc'][ul.crate_type] += len(ul.rtis)
            self.model.rdc_agent.receive_uls(uls_to_dispatch)
        
    def step(self):
        self.process_sales()
        self.extract_rtis()
        
        for rti in self.displayed_rtis_rpos:
            rti.detention_time += 1

        for rtis in self.reverse_stock_rpos.values():
            for rti in rtis:
                rti.detention_time += 1


# =============================================================================
# MODEL CLASS
# =============================================================================

class CLSC_Model(mesa.Model):
    def __init__(self, results_dir=None, run_timestamp=None):
        super().__init__()
        
        self.timestamp = run_timestamp if run_timestamp else datetime.now().strftime("%Y.%m.%d_%H.%M")
        self.results_dir = results_dir if results_dir else f"run_{self.timestamp}"
        self.log_filename = os.path.join(self.results_dir, f"sim_log_{self.timestamp}.txt")
        
        self.all_orders = []
        
        # POOLER
        self.pools = [Pooler_Agent(self, POOLER)]
        self.pool_agent = self.pools[0]
        
        # PRODUCERS
        self.products = []
        self.producers = []
        self.producers_by_id = {}
        for p_data in PRODUCERS:
            prod_obj = Product(
                name=p_data["product"],
                makes_dirty=p_data["makes_dirty"],
                compatible_crates=[CrateType[ct_name] for ct_name in p_data["compatible_crates"]]
            )
            self.products.append(prod_obj)
        
            pid = p_data["id"]
            if pid not in self.producers_by_id:
                p_agent = Producer_Agent(self, pid, prod_obj)
                self.producers.append(p_agent)
                self.producers_by_id[pid] = p_agent

        # RDC
        self.rdcs = [RDC_Agent(self, RDC)]
        self.rdc_agent = self.rdcs[0]
        
        # RPOS
        size_dist = ['big'] * N_RPOS_BIG + ['medium'] * N_RPOS_MEDIUM + ['small'] * N_RPOS_SMALL
        self.r_pos_agents = []
        for i in range(N_RPOS):
            rpos = RPOS_Agent(self, size_dist[i])
            self.r_pos_agents.append(rpos)
        
        self.reset_daily_log()
        
        reporters = {}
        
        for ct in CrateType:
            c_name = ct.name
            
            # --- STOCK ---
            reporters[f"Stock|POOL_WASHED|{c_name}"] = lambda m, c=ct: sum(len(ul.rtis) for ul in m.pool_agent.washed_stock_pool.get(c, []))
            reporters[f"Stock|POOL_UNWASHED|{c_name}"] = lambda m, c=ct: sum(len(ul.rtis) for ul in m.pool_agent.unwashed_stock_pool.get(c, []))
            reporters[f"Stock|POOL_BUFFER|{c_name}"] = lambda m, c=ct: sum(len(ul.rtis) for ul in m.pool_agent.processing_buffer if ul.crate_type == c)
            reporters[f"Stock|RDC_REVERSE|{c_name}"] = lambda m, c=ct: sum(len(ul.rtis) for ul in m.rdc_agent.reverse_stock_rdc.get(c, []))
            reporters[f"Stock|RPOS_DISPLAY|{c_name}"] = lambda m, c=ct: sum(1 for rpos in m.r_pos_agents for rti in rpos.displayed_rtis_rpos if rti.crate_type == c)
            reporters[f"Stock|RPOS_REVERSE|{c_name}"] = lambda m, c=ct: sum(len(rpos.reverse_stock_rpos.get(c, [])) for rpos in m.r_pos_agents)

            # --- INFLOWS & OUTFLOWS ---
            reporters[f"Flow|RDC|POOL|{c_name}"] = lambda m, c=ct: m.daily_log['movements']['rdc_to_pool'][c]
            reporters[f"Flow|RDC|RPOS|{c_name}"] = lambda m, c=ct: m.daily_log['movements']['rdc_to_pos'][c]
            reporters[f"Flow|RPOS|RDC|{c_name}"] = lambda m, c=ct: m.daily_log['movements']['pos_to_rdc'][c]

            # --- BACKORDERS ---
            reporters[f"Backorders|POOL_WASHED|{c_name}"] = lambda m, c=ct: sum(o.quantity * UL_SIZE for o in m.pool_agent.order_book if o.crate_type == c and o.needs_washed is True and m.steps >= (o.creation_step + o.lead_time))
            reporters[f"Backorders|POOL_UNWASHED|{c_name}"] = lambda m, c=ct: sum(o.quantity * UL_SIZE for o in m.pool_agent.order_book if o.crate_type == c and o.needs_washed is False and m.steps >= (o.creation_step + o.lead_time))

            # --- PROs METRICS ---
            for p in self.producers:
                p_id = p.producer_id
                reporters[f"Stock|{p_id}|{c_name}"] = lambda m, c=ct, pid=p_id: len(m.producers_by_id[pid].forward_stock_pro.get(c, []))
                reporters[f"Flow|POOL|{p_id}|{c_name}"] = lambda m, c=ct, pid=p_id: m.daily_log['movements']['pool_to_pro'][pid][c]
                reporters[f"Flow|{p_id}|RDC|{c_name}"] = lambda m, c=ct, pid=p_id: m.daily_log['movements']['pro_to_rdc'][pid][c]
                reporters[f"Backorders|{p_id}|{c_name}"] = lambda m, c=ct, pid=p_id: sum(o.quantity for o in m.producers_by_id[pid].order_book if o.crate_type == c and m.steps >= (o.creation_step + o.lead_time))

        self.datacollector = mesa.DataCollector(model_reporters=reporters)
        self.datacollector.collect(self)

    def reset_daily_log(self):
        self.daily_log = {
            'movements': {
                'pro_to_rdc': {p.producer_id: {ct: 0 for ct in CrateType} for p in self.producers},
                'pool_to_pro': {p.producer_id: {ct: 0 for ct in CrateType} for p in self.producers},
                'rdc_to_pos': {ct: 0 for ct in CrateType},
                'pos_to_rdc': {ct: 0 for ct in CrateType},
                'rdc_to_pool': {ct: 0 for ct in CrateType}
            }
        }

    def export_to_excel(self):
        filename = os.path.join(self.results_dir, f"sim_log_{self.timestamp}.xlsx")
        
        df_wide = self.datacollector.get_model_vars_dataframe()
        df_wide = df_wide.reset_index().rename(columns={"index": "Step"})
        
        cols_to_melt = [c for c in df_wide.columns if c.startswith(('Stock|', 'Flow|', 'Backorders|')) or c == 'Step']
        df_long = df_wide[cols_to_melt].melt(id_vars=["Step"], var_name="Metric", value_name="Quantity")
        
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            
            # --- SHEET 1: STOCK ---
            df_stock = df_long[df_long['Metric'].str.startswith('Stock|')].copy()
            df_stock[['Category', 'Warehouse', 'Crate Type']] = df_stock['Metric'].str.split('|', expand=True)
            df_stock = df_stock[['Step', 'Warehouse', 'Crate Type', 'Quantity']].sort_values(by=['Step', 'Warehouse', 'Crate Type'])
            df_stock.to_excel(writer, sheet_name='Stock', index=False)
            
            # --- SHEET 2: FLOWS ---
            df_flow = df_long[df_long['Metric'].str.startswith('Flow|')].copy()
            df_flow[['Category', 'Origin', 'Destination', 'Crate Type']] = df_flow['Metric'].str.split('|', expand=True)
            df_flow = df_flow[['Step', 'Origin', 'Destination', 'Crate Type', 'Quantity']].sort_values(by=['Step', 'Origin', 'Destination', 'Crate Type'])
            df_flow.to_excel(writer, sheet_name='Flows', index=False)
            
            # --- SHEET 3: BACKORDERS ---
            df_back = df_long[df_long['Metric'].str.startswith('Backorders|')].copy()
            df_back[['Category', 'Warehouse', 'Crate Type']] = df_back['Metric'].str.split('|', expand=True)
            df_back = df_back[['Step', 'Warehouse', 'Crate Type', 'Quantity']].sort_values(by=['Step', 'Warehouse', 'Crate Type'])
            df_back.to_excel(writer, sheet_name='Backorders', index=False)
            
            # --- SHEET 4: ORDERS ---
            if self.all_orders:
                orders_data = []
                for o in self.all_orders:
                    orders_data.append({
                        'Step': o.creation_step,
                        'Order ID': o.order_id,
                        'Issuer': o.issuer,
                        'Supplier': o.supplier,
                        'Crate Type': o.crate_type.name,
                        'Quantity': o.quantity,
                        'UoM': o.uom,
                        'Lead Time': o.lead_time,
                        'Needs Wash': o.needs_washed if o.needs_washed is not None else 'N/A'
                    })
                df_orders = pd.DataFrame(orders_data)
                df_orders = df_orders.sort_values(by=['Step', 'Issuer'])
                df_orders.to_excel(writer, sheet_name='Orders', index=False)
                
        print(f"\nSimulation log exported successfully: {filename}")
    
    def step(self):

        self.reset_daily_log()
        
        # 1        
        self.rdc_agent.generate_orders()
        
        # 2
        for p in self.producers:
            p.step()
        
        # 3
        self.rdc_agent.dispatch_rtis()
        
        # 4
        for rpos in self.r_pos_agents: 
            rpos.step()
        
        # 5
        self.rdc_agent.extract_uls()
        self.rdc_agent.step()
        
        # 6
        self.pool_agent.step()
        
        for agent in self.agents:
            if isinstance(agent, RTI_Agent):
                agent.transported_this_step = False
                
        self.datacollector.collect(self)
        
        
# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("\nSimulation starting...\n")
    
    current_timestamp = datetime.now().strftime("%Y.%m.%d_%H.%M")
    run_folder = f"run_{current_timestamp}"
    os.makedirs(run_folder, exist_ok=True)
    
    model = CLSC_Model(results_dir=run_folder, run_timestamp=current_timestamp)
    
    for i in range(SIMULATION_STEPS):
        model.step()
        
        progress_pct = ((i+1) / SIMULATION_STEPS) * 100
        bar_length = 70
        filled = int(bar_length * (i+1) / SIMULATION_STEPS)
        bar = '█' * filled + '░' * (bar_length - filled)
        print(f"\r[{bar}] {progress_pct:.1f}% | Step (Day) {i+1:3d}/{SIMULATION_STEPS}", end='', flush=True)
        
    print("\n\nSimulation completed.")
    model.export_to_excel()