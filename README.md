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

## Prerequisites

It is recommended to use **Anaconda** or **Miniconda** to manage the virtual environment.

```bash
# Create and activate a new Conda environment
conda create -n clsc_sim python=3.10
conda activate clsc_sim

# Install required dependencies
pip install mesa pandas openpyxl
```

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


