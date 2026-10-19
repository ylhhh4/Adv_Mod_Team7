import os
from datetime import datetime
from config import SimulationConfig
from model import CLSC_Model

# IMPROVEMENT: Created a clean execution entry point. 
# This prevents the simulation from running automatically when modules are imported elsewhere.
if __name__ == "__main__":
    print("\nSimulation starting...\n")
    
    config = SimulationConfig()
    current_timestamp = datetime.now().strftime("%Y.%m.%d_%H.%M")
    run_folder = f"run_{current_timestamp}"
    os.makedirs(run_folder, exist_ok=True)
    
    # Instantiate the model
    model = CLSC_Model(config=config, results_dir=run_folder, run_timestamp=current_timestamp)
    
    # Run the simulation loop
    for i in range(config.SIMULATION_STEPS):
        model.step()
        progress_pct = ((i+1) / config.SIMULATION_STEPS) * 100
        filled = int(70 * (i+1) / config.SIMULATION_STEPS)
        print(f"\r[{'█' * filled}{'░' * (70 - filled)}] {progress_pct:.1f}% | Step (Day) {i+1:3d}/{config.SIMULATION_STEPS}", end='', flush=True)
        
    print("\n\nSimulation completed.")
    model.export_to_excel()
