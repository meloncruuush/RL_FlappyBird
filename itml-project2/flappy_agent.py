from multiprocessing.dummy import active_children
import os
import time
from ple.games.flappybird import FlappyBird
from ple import PLE
import csv 
import random
import numpy as np
import matplotlib.pyplot as plt
from math import floor
import pandas as pd
import seaborn as sns
from typing import Dict, Tuple

import abc

class FlappyAgent(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def __init__(self):
        pass

    def reward_values(self) -> Dict[str, float]:
        """ returns the reward values used for training
        
            Note: These are only the rewards used for training.
            The rewards used for evaluating the agent will always be
            1 for passing through each pipe and 0 for all other state
            transitions.
        """
        return {"positive": 1.0, "tick": 0.0, "loss": -5.0} 

    def translate_int(self, value: int, leftMin: int, leftMax: int, rightMin: int, rightMax: int) -> int:
        # Figure out how 'wide' each range is
        leftSpan: int = leftMax - leftMin
        rightSpan: int = rightMax - rightMin

        # Convert the left range into a 0-1 range (float)
        valueScaled: float = float(value - leftMin) / float(leftSpan)

        # Convert the 0-1 range into a value in the right range.
        return max(min(floor(rightMin + (valueScaled * rightSpan)), rightMax), rightMin)
    
    def state_to_internal_state(self, state: Dict[str, int]) -> Tuple[int, int, int, int]:
        # make a method that maps a game state to your discretized version of it, e.g., 
        # state_to_internal_state(state). 
        # The internal (discretized) version of a state should be kept in a data structure 
        # that can be easily used as a key in a dict (e.g., a tuple).

        player_y: int = state['player_y']
        next_pipe_top_y: int = state['next_pipe_top_y']
        next_pipe_dist_to_player: int = state['next_pipe_dist_to_player']
        player_vel: int = state['player_vel']

        player_y: int = self.translate_int(player_y, 0, 512, 0, 15)
        next_pipe_top_y: int = self.translate_int(next_pipe_top_y, 0, 512, 0, 15)
        next_pipe_dist_to_player: int = self.translate_int(next_pipe_dist_to_player, 0, 288, 0, 15)

        if not(0 <= player_y <= 15 and 0 <= next_pipe_top_y <= 15 and 0 <= next_pipe_dist_to_player <= 15):
            raise Exception

        return (player_y, next_pipe_top_y, next_pipe_dist_to_player, player_vel)

    @abc.abstractmethod
    def observe(self, s1, action, reward, s2, end):
        """ this function is called during training on each step of the game where
            the state transition is going from state s1 with action a to state s2 and
            yields the reward r. If s2 is a terminal state, end==True, otherwise end==False.
            
            Unless a terminal state was reached, two subsequent calls to observe will be for
            subsequent steps in the same episode. That is, s1 in the second call will be s2
            from the first call.
            """
        pass

    @abc.abstractmethod
    def training_policy(self, state):
        """ Returns the index of the action that should be done in state while training the agent.
            Possible actions in Flappy Bird are 0 (flap the wing) or 1 (do nothing).

            training_policy is called once per frame in the game while training
        """
        pass

    @abc.abstractmethod
    def policy(self, state):
        """ Returns the index of the action that should be done in state when training is completed.
            Possible actions in Flappy Bird are 0 (flap the wing) or 1 (do nothing).

            policy is called once per frame in the game (30 times per second in real-time)
            and needs to be sufficiently fast to not slow down the game.
        """
        pass

    def plot(self, what):
        data = [k + tuple(self.q_values[k]) for k in self.q_values.keys()]
        if self.fig == None:
            self.fig = plt.figure()
        else:
            plt.figure(self.fig.number)
        self.fig.show()
        self.fig.canvas.draw()
        self.fig, ax = plt.subplots(figsize=(20, 20))
        df = pd.DataFrame(data=data, columns=('next_pipe_top_y', 'player_y', 'player_vel', 'next_pipe_dist_to_player', 'q_flap', 'q_noop'))
        df['delta_y'] = df['player_y'] - df['next_pipe_top_y']
        df['v'] = df[['q_noop', 'q_flap']].max(axis=1)
        df['pi'] = (df[['q_noop', 'q_flap']].idxmax(axis=1) == 'q_flap')*1
        selected_data = df.groupby(['delta_y','next_pipe_dist_to_player'], as_index=False).mean()
        plt.clf()
        with sns.axes_style("white"):
            if what in ('q_flap', 'q_noop', 'v'):
                ax = sns.heatmap(selected_data.pivot('delta_y','next_pipe_dist_to_player',what), vmin=-5, vmax=5, cmap='coolwarm', annot=True, fmt='.2f')
            elif what == 'pi':
                ax = sns.heatmap(selected_data.pivot('delta_y','next_pipe_dist_to_player', 'pi'), vmin=0, vmax=1, cmap='coolwarm')
            ax.invert_xaxis()
            ax.set_title(what + ' after ' + str(self.nbr_of_frames) + ' frames / ' + str(self.nbr_of_episodes) + ' episodes')
        plt.ion()
        plt.show()
        plt.draw()
        plt.pause(0.1)
        self.fig.savefig(what + '_' + 'plot.jpg', bbox_inches='tight', dpi=150)


class QlearningAgent(FlappyAgent):
    def __init__(self):
        # TODO: you may need to do some initialization for your agent here
        self.q_values: Dict[Tuple[int, int, int, int], Dict[int, float]] = {}
        self.learning_rate: float = 0.1 # alpha
        self.discount: float = 1 # gamma 
        self.epsilon: float = 0.1
        self.fig = None
        self.nbr_of_episodes = 0
        self.nbr_of_frames = 0
    
    def get_q(self, state: Dict[str, int], action: int) -> float: 
        # Returns Q(s,a) based on a state and action pair
        
        internal_state: Tuple[int, int, int, int] = self.state_to_internal_state(state)
        
        if internal_state in self.q_values:
            action_reward_pair: Dict[int, float] = self.q_values[internal_state]

            if action in action_reward_pair:
                value: float = self.q_values[internal_state][action]

                return value
                
        return 0.0

    def set_q(self, state: Dict[str, int], action: int, value: float) -> None:
        # Sets a value to Q(s,a) based on a state and action pair

        internal_state: Tuple[int, int, int, int] = self.state_to_internal_state(state)

        if not(internal_state in self.q_values):
            self.q_values[internal_state] = dict()

        self.q_values[internal_state][action] = value
    
    def observe(self, s1: Dict[str, int], action: int, reward: float, s2: Dict[str, int], end: bool) -> None:
        """ this function is called during training on each step of the game where
            the state transition is going from state s1 with action a to state s2 and
            yields the reward r. If s2 is a terminal state, end==True, otherwise end==False.
            
            Unless a terminal state was reached, two subsequent calls to observe will be for
            subsequent steps in the same episode. That is, s1 in the second call will be s2
            from the first call.
            """

        current_state_value: float = self.get_q(s1, action)

        if current_state_value is None:
            current_state_value = 0
        
        # Updates Q(s, a) with a new value
        # value: float = current_state_value + self.learning_rate * (reward +  self.discount * self.action_with_max_value(s2)  - current_state_value)

        o_value: float = current_state_value + self.learning_rate * (reward + self.discount * self.get_q(s2, self.action_with_max_value(s2)) - self.get_q(s1, action))

        # if value != o_value:
        #     print(value, o_value)

        self.set_q(s1, action, o_value)  

        if end:
            self.nbr_of_episodes += 1

    def action_with_max_value(self, state: Dict[str, int]) -> int:

        s_0 = self.get_q(state, 0)
        s_1 = self.get_q(state, 1)

        # TODO 
        # need to handle the case if there's no values for either s_0 or s_1

        if s_0 is None:
            print("no 0")
            s_0 = 0
        if s_1 is None:
            print("no 1")
            s_1 = 0
        if s_1 > s_0:
            # print("1!!")
            return 1
        else:
            # print("0!!")
            return 0

    def training_policy(self, state: Dict[str, int]) -> int:
        """ Returns the index of the action that should be done in state while training the agent.
            Possible actions in Flappy Bird are 0 (flap the wing) or 1 (do nothing).

            training_policy is called once per frame in the game while training
        """

        greedy: bool = np.random.choice([False, True], p=[self.epsilon, 1 - self.epsilon])
        # greedy = False

        if greedy:
            action = self.action_with_max_value(state)
        else:
            action = random.randint(0, 1)
        # action = [0, 0, 1, 1, 1, 1, 1][random.randint(0, 6)]

        return action

    def policy(self, state: Dict[str, int]) -> int:
        """ Returns the index of the action that should be done in state when training is completed.
            Possible actions in Flappy Bird are 0 (flap the wing) or 1 (do nothing).

            policy is called once per frame in the game (30 times per second in real-time)
            and needs to be sufficiently fast to not slow down the game.
        """

        return self.action_with_max_value(state)

def run_game(nb_episodes: int, agent: FlappyAgent) -> None:
    """ Runs nb_episodes episodes of the game with agent picking the moves.
        An episode of FlappyBird ends with the bird crashing into a pipe or going off screen.
    """

    reward_values = agent.reward_values()
    
    # env = PLE(FlappyBird(), fps=30, display_screen=True, force_fps=False, rng=None,
    #         reward_values = reward_values)
    # TODO: to speed up training change parameters of PLE as follows:
    # display_screen=False, force_fps=True 
    env: PLE = PLE(FlappyBird(), fps=30, display_screen=True, force_fps=False, rng=None,
            reward_values = reward_values)
    env.init()

    score: int = 0

    while nb_episodes > 0:
        action: int = agent.policy(env.game.getGameState())

        # s1: Dict[str, int] = env.getGameState()

        # step the environment
        thing: int = env.act(env.getActionSet()[action])

        reward: int = thing

        end: bool = env.game_over()
        # s2 = env.getGameState()
        # agent.observe(s1, action, reward, s2, end)

        score += reward
        
        # reset the environment if the game is over
        if end:
            env.reset_game()
            nb_episodes -= 1
            score = 0

def train(nb_episodes: int, agent: FlappyAgent) -> None:
    reward_values: Dict[str, float] = agent.reward_values()
    

    # Lok for agent, create folder for it if none exist
    # env = PLE(FlappyBird(), fps=30, display_screen=False, force_fps=False, rng=None,
    #         reward_values = reward_values)
    
    # Faster:
    env: PLE = PLE(FlappyBird(), fps=30, display_screen=False, force_fps=True, rng=None,
            reward_values = reward_values)

    env.init()

    score: int = 0
    prev_time = 0
    while nb_episodes > 0:
        
        # pick an action
        state: Dict[str, int] = env.game.getGameState()
        action: int = agent.training_policy(state)

        # step the environment
        thing: int = env.act(env.getActionSet()[action])

        reward: int = thing

        newState = env.game.getGameState()
        agent.observe(state, action, reward, newState, env.game_over())

        score += reward

        # reset the environment if the game is over
        if env.game_over():
            # print("-------------")
            # print("number of q values", len(agent.q_values))
            # print("NEW EPISODE:", nb_episodes)
            # print("score for this episode: %d" % score)
            if nb_episodes % 1000 == 0:
                curr_time = time.time()
                print(curr_time - prev_time, ":", nb_episodes, "-", len(agent.q_values))
                prev_time = curr_time
            env.reset_game()
            nb_episodes -= 1
            score = 0
        
def write(agent, filestr):

    # WRITE
    if not os.path.exists("results"):
        os.mkdir("results")

    while os.path.exists(filestr):
        filestr =+ "_new"

    filestr += ".csv"

    w = csv.writer(open(filestr, "w"))
    for key, val in agent.q_values.items():
        zero = ""
        one = ""
        if val != None:
            if 0 in val :
                zero = val[0]
            if 1 in val:
                one = val[1]
        a, b, c, d = key    
        w.writerow([a, b, c, d, zero, one])

def read(filestr):
    qvals = dict()
    # READ
    with open(filestr + ".csv", mode ='r') as file:
        csvFile = csv.reader(file)
        
        # displaying the contents of the CSV file
        for line in csvFile:
            if line == []:
                continue
            a, b, c, d, zero, one = line

            t = dict()

            if zero != "":
                t[0] = float(zero)
            if one != "":
                t[1] = float(one)

            qvals[(int(a), int(b), int(c), float(d))] = t

    return qvals
    

def main() -> None:
        # SETUP
    iterations: int = 4000
    agent: FlappyAgent  = QlearningAgent()
    filestr: str = 'results/qvalues_' + str(iterations)
   
    train(iterations, agent)
    write(agent, filestr)

    vals = read("results/qvalues_4000")
    print(filestr)
    vals = read(filestr)
    agent.q_values = vals

    print(len(agent.q_values))

    agent.plot("pi")
    run_game(10, agent)
    agent.plot("pi")

main()