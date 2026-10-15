import uuid
import random
import mesa
from typing import List, Dict, Optional
from config import CrateType, Product, OrderLine, UnitLoad, LocationType

class RTI_Agent(mesa.Agent):
    def __init__(self, model, crate_type: CrateType = None, washed: bool = True, 
                 location: LocationType = LocationType.POOL, is_filled: bool = False, 
                 product: Optional[Product] = None):
        super().__init__(model)
        self.crate_type = crate_type if crate_type else list(CrateType)[0]
        self.rti_id = str(uuid.uuid4())
        self.product = product
        self.is_filled = is_filled
        self.under_processing = False
        self.washed = washed
        self.location = location
        self.arrival_step = model.steps
        self.broken = False
        self.dirty = False
        
class Pooler_Agent(mesa.Agent):
    def __init__(self, model, pool_id: str):
        super().__init__(model)
        self.pool_id = pool_id
        cfg = self.model.config
        
        self.washed_stock_pool = {
            ct: [UnitLoad(crate_type=ct, rtis=[RTI_Agent(self.model, ct, washed=True, location=LocationType.POOL) for _ in range(cfg.UL_SIZE)]) for _ in range(cfg.INIT_POOL_WASHED_UL)]
            for ct in CrateType
        }
        self.unwashed_stock_pool = {
            ct: [UnitLoad(crate_type=ct, rtis=[RTI_Agent(self.model, ct, washed=False, location=LocationType.POOL) for _ in range(cfg.UL_SIZE)]) for _ in range(cfg.INIT_POOL_UNWASHED_UL)]
            for ct in CrateType
        }
        self.processing_buffer = []
        self.processing_times = {}      
        self.processing_lead_time = cfg.POOL_PROCESSING_TIME
        self.order_book: List[OrderLine] = []
        
    def receive_orders(self, order: OrderLine):
        self.order_book.append(order)
          
    def extract_uls(self, crate_type: CrateType, needs_washed: Optional[bool], quantity_uls: int) -> List[UnitLoad]:      
        primary_stock = self.washed_stock_pool[crate_type] if needs_washed else self.unwashed_stock_pool[crate_type]
        secondary_stock = [] if needs_washed else self.washed_stock_pool[crate_type]
            
        primary_available = len(primary_stock)
        selected_uls = []
        if primary_available >= quantity_uls:
            selected_uls = primary_stock[:quantity_uls]
            del primary_stock[:quantity_uls]
        else:
            selected_uls.extend(primary_stock)
            primary_stock.clear()
            needed = quantity_uls - primary_available
            if len(secondary_stock) >= needed:
                selected_uls.extend(secondary_stock[:needed])
                del secondary_stock[:needed]
            else:
                selected_uls.extend(secondary_stock)
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
                
                target_pro = self.model.producers_by_id[order.issuer]
                target_pro.receive_uls(extracted_uls)
                self.model.daily_log['movements']['pool_to_pro'][order.issuer][order.crate_type] += extracted_qty_uls * self.model.config.UL_SIZE
            
            shortage_uls = order.quantity - extracted_qty_uls
            if shortage_uls > 0:
                order.quantity = shortage_uls
            else:
                self.order_book.remove(order)            

    def receive_uls(self, uls: List[UnitLoad]):
        current_step = self.model.steps
        for ul in uls:
            for rti in ul.rtis:                               
                self.evaluate_rti_condition(rti)
                rti.location = LocationType.POOL
                rti.arrival_step = current_step
        self.screen_uls(uls, current_step)
        
    def screen_uls(self, uls: List[UnitLoad], current_step: int):
        num_uls_to_screen = min(len(uls), self.model.config.POOL_SCREENING_CAPACITY)
        uls_to_screen = uls[:num_uls_to_screen] if num_uls_to_screen > 0 else []
        uls_to_bypass = uls[num_uls_to_screen:]
                
        for ul in uls_to_screen:
            self.processing_buffer.append(ul)
            self.processing_times[ul.id] = current_step
            for rti in ul.rtis:
                rti.under_processing = True
        
        for ul in uls_to_bypass:
            self.unwashed_stock_pool[ul.crate_type].append(ul)
            
    def process_uls(self):
        current_time = self.model.steps
        ready_uls = [ul for ul in self.processing_buffer if current_time - self.processing_times.get(ul.id, current_time) >= self.processing_lead_time]
        
        for ul in ready_uls:
            for rti in ul.rtis:
                self.process_rti(rti)
                rti.under_processing = False
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
                
    def evaluate_rti_condition(self, rti: RTI_Agent):
        if random.random() < self.model.config.RTI_BREAKAGE_RATE:
            rti.broken = True
        if not rti.dirty and rti.product is not None and rti.product.makes_dirty:
            rti.dirty = True
        rti.product = None
    
    def step(self):
        self.process_uls()
        self.fulfill_orders()

class Producer_Agent(mesa.Agent):
    def __init__(self, model, producer_id: str, product: Product):
        super().__init__(model)
        self.producer_id = producer_id
        self.product = product
        self.compatible_crates = set(self.product.compatible_crates)
        self.order_book: List[OrderLine] = []
        self.on_order_from_pool = {ct: 0 for ct in CrateType}
        cfg = self.model.config
        self.forward_stock_pro = {
            ct: [RTI_Agent(self.model, ct, washed=False, location=LocationType.PRO) for _ in range(cfg.INIT_PRO_UL * cfg.UL_SIZE)] if ct in self.compatible_crates else []
            for ct in CrateType
        }
                                
    def generate_orders(self):
        cfg = self.model.config
        for ct in self.compatible_crates:
            physical_stock = len(self.forward_stock_pro[ct])
            transit_stock = self.on_order_from_pool[ct]
            backordered_stock = sum(o.quantity for o in self.order_book if o.crate_type == ct)
            inventory_position = physical_stock + transit_stock - backordered_stock
            
            if inventory_position <= cfg.PRO_REORDER_POINT:
                self.on_order_from_pool[ct] += cfg.PRO_REORDER_QTY * cfg.UL_SIZE
                requires_washing = random.random() < cfg.WASHING_REQUIREMENT_RATE
                
                order = OrderLine(
                    issuer=self.producer_id, supplier=self.model.pool_agent.pool_id, order_id=str(uuid.uuid4()),
                    crate_type=ct, quantity=cfg.PRO_REORDER_QTY, uom='UL', lead_time=cfg.PRO_ORDER_LT,
                    creation_step=self.model.steps, needs_washed=requires_washing
                )
                self.model.pool_agent.receive_orders(order)
                self.model.all_orders.append({
                    'Step': order.creation_step, 'Order ID': order.order_id, 'Issuer': order.issuer,
                    'Supplier': order.supplier, 'Crate Type': order.crate_type.name, 'Quantity': order.quantity,
                    'UoM': order.uom, 'Lead Time': order.lead_time, 'Needs Wash': order.needs_washed
                })
    
    def receive_uls(self, uls: List[UnitLoad]):
        if not uls: return
        current_step = self.model.steps
        for ul in uls:
            for rti in ul.rtis:
                self.on_order_from_pool[rti.crate_type] = max(0, self.on_order_from_pool[rti.crate_type] - 1)
                rti.location = LocationType.PRO
                rti.washed = False
                rti.arrival_step = current_step
                self.forward_stock_pro[rti.crate_type].append(rti)
        
    def receive_orders(self, order: OrderLine):
        self.order_book.append(order)

    def extract_rtis(self, quantity: int, crate_type: CrateType) -> List[RTI_Agent]:
        available = self.forward_stock_pro[crate_type]
        qty_to_sample = min(quantity, len(available))
        if qty_to_sample == 0: return []
        
        rtis_to_send = available[:qty_to_sample]
        del available[:qty_to_sample]
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
                self.model.rdc_agent.receive_rtis(extracted_rtis)
                self.model.daily_log['movements']['pro_to_rdc'][self.producer_id][order.crate_type] += extracted_qty
            
            shortage = order.quantity - extracted_qty
            if shortage > 0: order.quantity = shortage
            else: self.order_book.remove(order)

    def step(self):
        self.fulfill_orders()
        self.generate_orders()

class RDC_Agent(mesa.Agent):
    def __init__(self, model, rdc_id: str):
        super().__init__(model)
        self.rdc_id = rdc_id
        self.forward_rtis_received_this_step = []
        cfg = self.model.config
        comp_prods = {ct: [p for p in self.model.products if ct in p.compatible_crates] for ct in CrateType}
        
        self.reverse_stock_rdc = {
            ct: [
                UnitLoad(crate_type=ct, rtis=[
                    RTI_Agent(self.model, ct, washed=False, location=LocationType.R_DC, is_filled=False, 
                              product=random.choice(comp_prods[ct]) if comp_prods[ct] else None) 
                    for _ in range(cfg.UL_SIZE)]) 
                for _ in range(cfg.INIT_RDC_UL)
            ]
            for ct in CrateType
        }
        
    def generate_orders(self):
        cfg = self.model.config
        total_demand = max(0, int(random.gauss(cfg.RDC_DAILY_DEMAND_MEAN, cfg.RDC_DAILY_DEMAND_STD)))
        if total_demand == 0: return

        remaining_demand = total_demand
        while remaining_demand > 0:
            qty_to_request = min(remaining_demand, random.randint(500, 1000))
            potential_remainder = remaining_demand - qty_to_request
            if 0 < potential_remainder < 100: qty_to_request += potential_remainder
            remaining_demand -= qty_to_request

            target_producer = random.choice(self.model.producers)
            product = target_producer.product
            crate_type = random.choice(product.compatible_crates)
            lead_time = random.randint(1, 3)

            order = OrderLine(
                issuer=self.rdc_id, supplier=target_producer.producer_id, order_id=str(uuid.uuid4()),
                product=product, crate_type=crate_type, quantity=qty_to_request,
                uom='RTI', lead_time=lead_time, creation_step=self.model.steps
            )
            self.model.all_orders.append({
                'Step': order.creation_step, 'Order ID': order.order_id, 'Issuer': order.issuer,
                'Supplier': order.supplier, 'Crate Type': order.crate_type.name, 'Quantity': order.quantity,
                'UoM': order.uom, 'Lead Time': order.lead_time, 'Needs Wash': 'N/A'
            })
            target_producer.receive_orders(order)
        
    def receive_rtis(self, rtis: List[RTI_Agent]):
        current_step = self.model.steps
        for rti in rtis:
            rti.location = LocationType.R_DC
            rti.arrival_step = current_step
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
        
        allocation = self.allocate_rtis(rtis)
        for rpos, rti_list in allocation.items():
            for rti in rti_list:
                rti.location = LocationType.TRANSPORT
            rpos.receive_rtis(rti_list)
    
    def receive_uls(self, uls: List[UnitLoad]):
        current_step = self.model.steps
        for ul in uls:            
            for rti in ul.rtis:
                rti.location = LocationType.R_DC
                rti.arrival_step = current_step
            self.reverse_stock_rdc[ul.crate_type].append(ul)
                
    def extract_uls(self):
        all_available_uls = [ul for uls in self.reverse_stock_rdc.values() for ul in uls]
        num_trucks = len(all_available_uls) // self.model.config.TRUCK_CAPACITY
        if num_trucks == 0: return
            
        uls_to_ship = all_available_uls[:num_trucks * self.model.config.TRUCK_CAPACITY]
        for ul in uls_to_ship:
            self.reverse_stock_rdc[ul.crate_type].remove(ul)
            for rti in ul.rtis:
                rti.location = LocationType.TRANSPORT
            self.model.daily_log['movements']['rdc_to_pool'][ul.crate_type] += len(ul.rtis)
            
        self.model.pool_agent.receive_uls(uls_to_ship)

class RPOS_Agent(mesa.Agent):
    def __init__(self, model, size: str):
        super().__init__(model)
        self.size = size
        self.display_time = self.model.config.RPOS_DISPLAY_TIME[size]
        self.reverse_stock_rpos = {ct: [] for ct in CrateType}
        self.displayed_rtis_rpos = [
            RTI_Agent(self.model, ct, washed=False, location=LocationType.R_POS, is_filled=True)
            for ct in CrateType for _ in range(self.model.config.INIT_RPOS_RTI)
        ]
    
    def receive_rtis(self, rtis: List[RTI_Agent]):
        current_step = self.model.steps
        for rti in rtis:
            rti.arrival_step = current_step
            rti.location = LocationType.R_POS
            self.displayed_rtis_rpos.append(rti)
    
    def process_sales(self):
        current_step = self.model.steps
        ready = [rti for rti in self.displayed_rtis_rpos if current_step - rti.arrival_step >= self.display_time]
        if ready:
            self.displayed_rtis_rpos = [rti for rti in self.displayed_rtis_rpos if rti not in ready]
            for rti in ready:
                rti.is_filled = False
                self.reverse_stock_rpos[rti.crate_type].append(rti)
            
    def extract_rtis(self):
        uls_to_dispatch = []
        cfg = self.model.config
        for ct in CrateType:
            available_rtis = self.reverse_stock_rpos[ct]
            num_full_uls = len(available_rtis) // cfg.UL_SIZE
            
            for _ in range(num_full_uls):
                rtis_for_ul = available_rtis[:cfg.UL_SIZE]
                self.reverse_stock_rpos[ct] = available_rtis[cfg.UL_SIZE:]
                available_rtis = self.reverse_stock_rpos[ct]
                
                for rti in rtis_for_ul: rti.location = LocationType.TRANSPORT
                uls_to_dispatch.append(UnitLoad(crate_type=ct, rtis=rtis_for_ul))
                
        if uls_to_dispatch:
            for ul in uls_to_dispatch:
                self.model.daily_log['movements']['pos_to_rdc'][ul.crate_type] += len(ul.rtis)
            self.model.rdc_agent.receive_uls(uls_to_dispatch)
        
    def step(self):
        self.process_sales()
        self.extract_rtis()
