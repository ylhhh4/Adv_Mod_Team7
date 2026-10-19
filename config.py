import uuid
from enum import Enum
from typing import List, Dict, Optional
from dataclasses import dataclass, field

# IMPROVEMENT: Encapsulated all scattered global variables into a centralized SimulationConfig dataclass. 
# This allows for easy parameter sweeps and multi-scenario testing without modifying the source code.
@dataclass
class SimulationConfig:
    SIMULATION_STEPS: int = 365
    CRATE_TYPE_NAMES: List[str] = field(default_factory=lambda: ['TYPE_1', 'TYPE_2', 'TYPE_3', 'TYPE_4'])
    UL_SIZE: int = 200
    TRUCK_CAPACITY: int = 33
    PRO_REORDER_POINT: int = 5000
    PRO_REORDER_QTY_TRUCKS: int = 1
    PRO_ORDER_LT: int = 1
    WASHING_REQUIREMENT_RATE: float = 0.50
    RDC_DAILY_DEMAND_MEAN: int = 7000
    RDC_DAILY_DEMAND_STD: int = 1000
    RPOS_DISPLAY_TIME: Dict[str, int] = field(default_factory=lambda: {'big': 1, 'medium': 1, 'small': 2})
    RTI_BREAKAGE_RATE: float = 0.05
    POOL_SCREENING_CAPACITY: int = 20
    POOL_PROCESSING_TIME: int = 1
    
    INIT_POOL_WASHED_UL: int = 100
    INIT_POOL_UNWASHED_UL: int = 100
    INIT_PRO_UL: int = 50
    INIT_RDC_UL: int = 15
    INIT_RPOS_RTI: int = 260
    
    N_RPOS_BIG: int = 5
    N_RPOS_MEDIUM: int = 5
    N_RPOS_SMALL: int = 10

    @property
    def PRO_REORDER_QTY(self) -> int:
        return self.PRO_REORDER_QTY_TRUCKS * self.TRUCK_CAPACITY
        
    @property
    def N_RPOS(self) -> int:
        return self.N_RPOS_BIG + self.N_RPOS_MEDIUM + self.N_RPOS_SMALL

_crate_type_members = {name: name.lower() for name in ['TYPE_1', 'TYPE_2', 'TYPE_3', 'TYPE_4']}
CrateType = Enum('CrateType', _crate_type_members)

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

class UnitLoad:
    def __init__(self, crate_type: CrateType, rtis: List['RTI_Agent'] = None):
        self.id = str(uuid.uuid4())
        self.crate_type = crate_type
        self.rtis = rtis if rtis is not None else []
    
    def add_rti(self, rti: 'RTI_Agent'):
        self.rtis.append(rti)

class LocationType(Enum):
    POOL = "pool"
    PRO = "pro"
    R_DC = "r_dc"
    R_POS = "r_pos"
    TRANSPORT = "transport"
