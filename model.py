import os
import mesa
import pandas as pd
from datetime import datetime
from config import SimulationConfig, CrateType, Product
from agents import Pooler_Agent, Producer_Agent, RDC_Agent, RPOS_Agent, RTI_Agent

class CLSC_Model(mesa.Model):
    def __init__(self, config: SimulationConfig = None, results_dir=None, run_timestamp=None):
        super().__init__()
        self.config = config if config else SimulationConfig()
        
        self.timestamp = run_timestamp if run_timestamp else datetime.now().strftime("%Y.%m.%d_%H.%M")
        self.results_dir = results_dir if results_dir else f"run_{self.timestamp}"
        self.all_orders = []
        
        # Init Agents
        self.pools = [Pooler_Agent(self, "POOL_1")]
        self.pool_agent = self.pools[0]
        
        producers_data = [
            {"id": "PRO_1", "product": "Orange", "makes_dirty": False, "compatible_crates": ['TYPE_1', 'TYPE_3']},
            {"id": "PRO_2", "product": "Lemon", "makes_dirty": False, "compatible_crates": ['TYPE_2', 'TYPE_4']},
            {"id": "PRO_3", "product": "Apple", "makes_dirty": False, "compatible_crates": ['TYPE_3', 'TYPE_4']},
            {"id": "PRO_4", "product": "Banana", "makes_dirty": True, "compatible_crates": ['TYPE_2', 'TYPE_3']},
            {"id": "PRO_5", "product": "Peach", "makes_dirty": True, "compatible_crates": ['TYPE_1', 'TYPE_3']},
            {"id": "PRO_6", "product": "Plum", "makes_dirty": True, "compatible_crates": ['TYPE_2']},
            {"id": "PRO_7", "product": "Strawberry", "makes_dirty": True, "compatible_crates": ['TYPE_1', 'TYPE_4']}
        ]
        
        self.products = []
        self.producers = []
        self.producers_by_id = {}
        for p_data in producers_data:
            prod_obj = Product(name=p_data["product"], makes_dirty=p_data["makes_dirty"],
                               compatible_crates=[CrateType[ct_name] for ct_name in p_data["compatible_crates"]])
            self.products.append(prod_obj)
            p_agent = Producer_Agent(self, p_data["id"], prod_obj)
            self.producers.append(p_agent)
            self.producers_by_id[p_data["id"]] = p_agent

        self.rdcs = [RDC_Agent(self, "RDC_1")]
        self.rdc_agent = self.rdcs[0]
        
        size_dist = ['big'] * self.config.N_RPOS_BIG + ['medium'] * self.config.N_RPOS_MEDIUM + ['small'] * self.config.N_RPOS_SMALL
        self.r_pos_agents = [RPOS_Agent(self, size_dist[i]) for i in range(self.config.N_RPOS)]
        
        self.reset_daily_log()
        
        # Reporter Definitions
        reporters = {}
        for ct in CrateType:
            c_name = ct.name
            reporters[f"Stock|POOL_WASHED|{c_name}"] = lambda m, c=ct: sum(len(ul.rtis) for ul in m.pool_agent.washed_stock_pool.get(c, []))
            reporters[f"Stock|POOL_UNWASHED|{c_name}"] = lambda m, c=ct: sum(len(ul.rtis) for ul in m.pool_agent.unwashed_stock_pool.get(c, []))
            reporters[f"Stock|POOL_BUFFER|{c_name}"] = lambda m, c=ct: sum(len(ul.rtis) for ul in m.pool_agent.processing_buffer if ul.crate_type == c)
            reporters[f"Stock|RDC_REVERSE|{c_name}"] = lambda m, c=ct: sum(len(ul.rtis) for ul in m.rdc_agent.reverse_stock_rdc.get(c, []))
            reporters[f"Stock|RPOS_DISPLAY|{c_name}"] = lambda m, c=ct: sum(1 for rpos in m.r_pos_agents for rti in rpos.displayed_rtis_rpos if rti.crate_type == c)
            reporters[f"Stock|RPOS_REVERSE|{c_name}"] = lambda m, c=ct: sum(len(rpos.reverse_stock_rpos.get(c, [])) for rpos in m.r_pos_agents)
            
            reporters[f"Flow|RDC|POOL|{c_name}"] = lambda m, c=ct: m.daily_log['movements']['rdc_to_pool'][c]
            reporters[f"Flow|RDC|RPOS|{c_name}"] = lambda m, c=ct: m.daily_log['movements']['rdc_to_pos'][c]
            reporters[f"Flow|RPOS|RDC|{c_name}"] = lambda m, c=ct: m.daily_log['movements']['pos_to_rdc'][c]

            reporters[f"Backorders|POOL_WASHED|{c_name}"] = lambda m, c=ct: sum(o.quantity * m.config.UL_SIZE for o in m.pool_agent.order_book if o.crate_type == c and o.needs_washed is True and m.steps >= (o.creation_step + o.lead_time))
            reporters[f"Backorders|POOL_UNWASHED|{c_name}"] = lambda m, c=ct: sum(o.quantity * m.config.UL_SIZE for o in m.pool_agent.order_book if o.crate_type == c and o.needs_washed is False and m.steps >= (o.creation_step + o.lead_time))

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
        df_wide = self.datacollector.get_model_vars_dataframe().reset_index().rename(columns={"index": "Step"})
        
        cols_to_melt = [c for c in df_wide.columns if c.startswith(('Stock|', 'Flow|', 'Backorders|')) or c == 'Step']
        df_long = df_wide[cols_to_melt].melt(id_vars=["Step"], var_name="Metric", value_name="Quantity")
        
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            df_stock = df_long[df_long['Metric'].str.startswith('Stock|')].copy()
            df_stock[['Category', 'Warehouse', 'Crate Type']] = df_stock['Metric'].str.split('|', expand=True)
            df_stock[['Step', 'Warehouse', 'Crate Type', 'Quantity']].sort_values(by=['Step', 'Warehouse', 'Crate Type']).to_excel(writer, sheet_name='Stock', index=False)
            
            df_flow = df_long[df_long['Metric'].str.startswith('Flow|')].copy()
            df_flow[['Category', 'Origin', 'Destination', 'Crate Type']] = df_flow['Metric'].str.split('|', expand=True)
            df_flow[['Step', 'Origin', 'Destination', 'Crate Type', 'Quantity']].sort_values(by=['Step', 'Origin', 'Destination', 'Crate Type']).to_excel(writer, sheet_name='Flows', index=False)
            
            df_back = df_long[df_long['Metric'].str.startswith('Backorders|')].copy()
            df_back[['Category', 'Warehouse', 'Crate Type']] = df_back['Metric'].str.split('|', expand=True)
            df_back[['Step', 'Warehouse', 'Crate Type', 'Quantity']].sort_values(by=['Step', 'Warehouse', 'Crate Type']).to_excel(writer, sheet_name='Backorders', index=False)
            
            if self.all_orders:
                pd.DataFrame(self.all_orders).sort_values(by=['Step', 'Issuer']).to_excel(writer, sheet_name='Orders', index=False)
                
        print(f"\nSimulation log exported successfully: {filename}")
    
    def step(self):
        self.reset_daily_log()
        self.rdc_agent.generate_orders()
        for p in self.producers: p.step()
        self.rdc_agent.dispatch_rtis()
        for rpos in self.r_pos_agents: rpos.step()
        self.rdc_agent.extract_uls()
        self.pool_agent.step()
        self.datacollector.collect(self)
