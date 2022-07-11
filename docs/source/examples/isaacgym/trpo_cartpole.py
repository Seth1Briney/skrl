import isaacgym

import torch
import torch.nn as nn

# Import the skrl components to build the RL system
from skrl.models.torch import GaussianModel, DeterministicModel
from skrl.memories.torch import RandomMemory
from skrl.agents.torch.trpo import TRPO, TRPO_DEFAULT_CONFIG
from skrl.resources.preprocessors.torch import RunningStandardScaler
from skrl.trainers.torch import SequentialTrainer
from skrl.envs.torch import wrap_env
from skrl.envs.torch import load_isaacgym_env_preview2, load_isaacgym_env_preview4
from skrl.utils import set_seed


# set the seed for reproducibility
set_seed(42)


# Define the models (stochastic and deterministic models) for the agent using helper classes.
# - Policy: takes as input the environment's observation/state and returns an action
# - Value: takes the state as input and provides a value to guide the policy
class Policy(GaussianModel):
    def __init__(self, observation_space, action_space, device, clip_actions=False,
                 clip_log_std=True, min_log_std=-20, max_log_std=2):
        super().__init__(observation_space, action_space, device, clip_actions,
                         clip_log_std, min_log_std, max_log_std)

        self.net = nn.Sequential(nn.Linear(self.num_observations, 32),
                                 nn.ELU(),
                                 nn.Linear(32, 32),
                                 nn.ELU(),
                                 nn.Linear(32, self.num_actions))
        self.log_std_parameter = nn.Parameter(torch.zeros(self.num_actions))

    def compute(self, states, taken_actions):
        return self.net(states), self.log_std_parameter

class Value(DeterministicModel):
    def __init__(self, observation_space, action_space, device, clip_actions=False):
        super().__init__(observation_space, action_space, device, clip_actions)

        self.net = nn.Sequential(nn.Linear(self.num_observations, 32),
                                 nn.ELU(),
                                 nn.Linear(32, 32),
                                 nn.ELU(),
                                 nn.Linear(32, 1))

    def compute(self, states, taken_actions):
        return self.net(states)


# Load and wrap the Isaac Gym environment.
# The following lines are intended to support all versions (preview 2, 3 and 4). 
# It tries to load from preview 3/4, but if it fails, it will try to load from preview 2
try:
    env = load_isaacgym_env_preview4(task_name="Cartpole")   # preview 3 and 4 use the same loader
except Exception as e:
    print("Isaac Gym (preview 3/4) failed: {}\nTrying preview 2...".format(e))
    env = load_isaacgym_env_preview2("Cartpole")
env = wrap_env(env)

device = env.device


# Instantiate a RandomMemory as rollout buffer (any memory can be used for this)
memory = RandomMemory(memory_size=16, num_envs=env.num_envs, device=device)


# Instantiate the agent's models (function approximators).
# TRPO requires 2 models, visit its documentation for more details
# https://skrl.readthedocs.io/en/latest/modules/skrl.agents.trpo.html#spaces-and-models
models_trpo = {"policy": Policy(env.observation_space, env.action_space, device),
               "value": Value(env.observation_space, env.action_space, device)}

# Initialize the models' parameters (weights and biases) using a Gaussian distribution
for model in models_trpo.values():
    model.init_parameters(method_name="normal_", mean=0.0, std=0.1)   


# Configure and instantiate the agent.
# Only modify some of the default configuration, visit its documentation to see all the options
# https://skrl.readthedocs.io/en/latest/modules/skrl.agents.trpo.html#configuration-and-hyperparameters
cfg_trpo = TRPO_DEFAULT_CONFIG.copy()
cfg_trpo["rollouts"] = 16
cfg_trpo["learning_epochs"] = 6
cfg_trpo["mini_batches"] = 2
cfg_trpo["grad_norm_clip"] = 0.5
cfg_trpo["value_loss_scale"] = 2.0
cfg_trpo["lambda"] = 0.95
cfg_trpo["state_preprocessor"] = RunningStandardScaler
cfg_trpo["state_preprocessor_kwargs"] = {"size": env.observation_space, "device": device}
cfg_trpo["value_preprocessor"] = RunningStandardScaler
cfg_trpo["value_preprocessor_kwargs"] = {"size": 1, "device": device}
# logging to TensorBoard and write checkpoints each 16 and 125 timesteps respectively
cfg_trpo["experiment"]["write_interval"] = 16
cfg_trpo["experiment"]["checkpoint_interval"] = 125

agent = TRPO(models=models_trpo,
            memory=memory, 
            cfg=cfg_trpo, 
            observation_space=env.observation_space, 
            action_space=env.action_space,
            device=device)


# Configure and instantiate the RL trainer
cfg_trainer = {"timesteps": 2500, "headless": True, "progress_interval": 250}
trainer = SequentialTrainer(cfg=cfg_trainer, env=env, agents=agent)

# start training
trainer.train()
