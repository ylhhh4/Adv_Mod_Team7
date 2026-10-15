# Closed-Loop Supply Chain (CLSC) Simulation

This project is an agent-based simulation model built with [Mesa](https://mesa.readthedocs.io/), designed to simulate and analyze the operations of a closed-loop supply chain involving Returnable Transport Items (RTIs).

## Project Structure

The project has been refactored into a modular structure for better maintainability, scalability, and ease of parameter tuning.

* **`config.py`**
  Contains all the global parameters, enums (`CrateType`, `LocationType`), and core data structures (`SimulationConfig`, `Product`, `OrderLine`, `UnitLoad`). This is the central file to modify when performing parameter sweeps or scenario testing, keeping the configuration completely isolated from the simulation logic.

* **`agents.py`**
  Defines the behavior and logic of all the network nodes (agents) in the supply chain. It includes `RTI_Agent` (the containers), `Pooler_Agent` (washing and pooling facility), `Producer_Agent` (manufacturers), `RDC_Agent` (distribution centers), and `RPOS_Agent` (retail point of sales). 

* **`model.py`**
  Houses the `CLSC_Model` class which orchestrates the simulation environment. It handles reading the configuration, initializing all agents, defining the `DataCollector` metrics (Stock, Flow, Backorders), and managing the daily step logic and Excel output exportation.

* **`main.py`**
  The entry point of the application. It initializes the `SimulationConfig`, runs the time-step loop, displays a progress bar in the console, and triggers the final data export upon completion.

### Prerequisites

This project requires **Python 3.10**. You can manage the virtual environment and dependencies using either Conda or standard Python tools.

**Option 1: Using Conda (Recommended)**
Create and activate the environment directly from the provided configuration file:

```bash
# Create the environment from the yml file
conda env create -f environment.yml

# Activate the environment
conda activate clsc_sim_env
```
Option 2: Using pip
If you prefer pip, ensure you have Python 3.10 installed, create a virtual environment, and install the dependencies:

# Create a virtual environment
python -m venv venv

# Activate it (Windows)
.\venv\Scripts\activate
# Or on macOS/Linux: source venv/bin/activate

# Install required dependencies
pip install -r requirements.txt

## How to Run

Execute the simulation by running the `main.py` script:

```bash
python main.py
```

## Outputs
Upon completion, the simulation will automatically create a new timestamped directory (e.g., run_YYYY.MM.DD_HH.MM/). Inside this folder, you will find an Excel file (.xlsx) containing multiple sheets:

- **Stock**: Inventory levels across different nodes.

- **Flows**: Movements of RTIs between nodes.

- **Backorders**: Unfulfilled orders over time.

- **Orders**: A complete log of all generated order lines.


