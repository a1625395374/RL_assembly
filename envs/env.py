try:
    from ikpy.chain import Chain
    from ikpy.link import OriginLink, URDFLink
    import ikpy as ik
except ImportError:
    import sys
    sys.exit('The "ikpy" Python module is not installed. '
             'To run this sample, please upgrade "pip" and install ikpy with this command: "pip install ikpy"')

import math
from controller import Supervisor
import matplotlib.pyplot as plt
import numpy as np
import algorithms.calculations as cal
from gym import spaces

# Create the arm chain (robot).
armChain = Chain(name='arm', links=[
    OriginLink(),
    URDFLink(
        name="A motor",
        bounds=[-3.1415, 3.1415],
        translation_vector=[0, 0, 0.159498],
        orientation=[0, 0, 0],
        rotation=[0, 0, 1]
    ),
    URDFLink(
        name="B motor",
        bounds=[-1.5708, 2.61799],
        translation_vector=[0.178445, -0.122498, 0.334888],
        orientation=[0, 0, 0],
        rotation=[0, 1, 0]
    ),
    URDFLink(
        name="C motor",
        bounds=[-3.1415, 1.309],
        translation_vector=[-0.003447, -0.0267, 1.095594],
        orientation=[0, 0, 0],
        rotation=[0, 1, 0]
    ),
    URDFLink(
        name="D motor",
        bounds=[-6.98132, 6.98132],
        translation_vector=[0.340095, 0.149198, 0.174998],
        orientation=[0, 0, 0],
        rotation=[1, 0, 0]
    ),
    URDFLink(
        name="E motor",
        bounds=[-2.18166, 2.0944],
        translation_vector=[0.929888, 0, 0],
        orientation=[0, 0, 0],
        rotation=[0, 1, 0]
    ),
    URDFLink(
        name="F motor",
        bounds=[-3.1415, 3.1415],
        translation_vector=[0, 0, 0],
        orientation=[0, 0, 0],
        rotation=[1, 0, 0]
    )
])


class ArmEnv(object):

    def __init__(self, step_max=100, add_noise=False):

        self.observation_dim = 12
        self.action_dim = 6

        """ state """
        self.state = np.zeros(self.observation_dim)
        self.init_state = np.zeros(self.observation_dim)

        """ action """
        self.action_high_bound = 1
        self.action = np.zeros(self.action_dim)

        """ reward """
        self.step_max = step_max
        self.insert_depth = 40

        """setting"""
        self.add_noise = add_noise  # or True

        """information for action and state"""
        self.action_space = spaces.Box(low=-1, high=1,
                                       shape=(self.action_dim,), dtype=np.float32)
        self.observation_space = spaces.Box(low=-10, high=10,
                                            shape=(self.observation_dim,), dtype=np.float32)

        """Enable PD controler"""
        self.pd = True

        """Setup controllable variables"""
        self.movementMode = 1  # work under FK(0) or IK(1)

        """Timer"""
        self.timer = 0

        """Initialize the Webots Supervisor"""
        self.supervisor = Supervisor()
        self.timeStep = int(8)
        # TODO: It's there a way to start simulation automatically?

        '''enable world devices'''
        # Initialize the arm motors.
        self.motors = []
        for motorName in ['A motor', 'B motor', 'C motor', 'D motor', 'E motor', 'F motor']:
            motor = self.supervisor.getMotor(motorName)
            self.motors.append(motor)

        # Get the arm, target and hole nodes.
        self.target = self.supervisor.getFromDef('TARGET')
        self.arm = self.supervisor.getFromDef('ARM')
        self.hole = self.supervisor.getFromDef('HOLE')
        self.armEnd = self.supervisor.getFromDef('INIT')
        # Get the absolute position of the arm base and target.
        self.armPosition = self.arm.getPosition()
        self.targetPosition = self.target.getPosition()
        self.initPosition = self.armEnd.getPosition()
        # Get the translation field fo the hole
        self.hole_translation = self.hole.getField('translation')
        self.hole_rotation = self.hole.getField('rotation')
        # Get initial position of hole
        self.hole_init_position = self.hole_translation.getSFVec3f()
        self.hole_init_rotation = self.hole_rotation.getSFRotation()
        print("Hole init position", self.hole_init_position)
        print("Hole init rotation", self.hole_init_rotation)

        # get and enable sensors
        # Fxyz: N, Txyz: N*m
        self.fz_sensor = self.supervisor.getMotor('FZ_SENSOR')
        self.fz_sensor.enableForceFeedback(self.timeStep)
        self.fx_sensor = self.supervisor.getMotor('FX_SENSOR')
        self.fx_sensor.enableForceFeedback(self.timeStep)
        self.fy_sensor = self.supervisor.getMotor('FY_SENSOR')
        self.fy_sensor.enableForceFeedback(self.timeStep)
        self.tx_sensor = self.supervisor.getMotor('TX_SENSOR')
        self.tx_sensor.enableTorqueFeedback(self.timeStep)
        self.ty_sensor = self.supervisor.getMotor('TY_SENSOR')
        self.ty_sensor.enableTorqueFeedback(self.timeStep)
        self.tz_sensor = self.supervisor.getMotor('TZ_SENSOR')
        self.tz_sensor.enableTorqueFeedback(self.timeStep)
        self.FZ = self.fz_sensor.getForceFeedback()
        self.FX = self.fx_sensor.getForceFeedback()
        self.FY = self.fy_sensor.getForceFeedback()
        self.TX = self.tx_sensor.getTorqueFeedback()
        self.TY = self.ty_sensor.getTorqueFeedback()
        self.TZ = self.tz_sensor.getTorqueFeedback()

        """Initial Position of the robot"""
        # x/y/z in meters relative to world frame
        self.x = 0
        self.y = 0
        self.z = 0
        # alpha/beta/gamma in rad relative to initial orientation
        self.alpha = 0
        self.beta = 0
        self.gamma = 0

        """reset world"""
        self.reset()

    def step(self, action):
        self.supervisor.step(self.timeStep)

        self.timer += 1
        # read state
        uncode_state, self.state = self.__get_state()

        # adjust action to usable motion
        action = cal.actions(self.state, action, self.pd)
        # take actions
        self.__execute_action(action)

        # uncode_state, self.state = self.__get_state()
        # safety check
        safe = cal.safetycheck(self.state)
        # done and reward
        r, done = cal.reward_step(self.state, safe, self.timer)

        return self.state, uncode_state, r, done, safe

    def reset(self):
        """restart world"""
        # clear calculations
        cal.clear()

        print("*******************************world rested*******************************")

        '''set random position for hole'''
        hole_new_position = self.hole_init_position + (np.random.rand(3)-0.5) / 500
        hole_new_rotation = self.hole_init_rotation + (np.random.rand(4)-0.5) / 80
        # hole_new_position = self.hole_init_position + (np.array([0.01871559, 0.02142697, -0.06982981])) / 500
        # hole_new_rotation = self.hole_init_rotation + (np.array([0.01901839, -0.01341116, -0.03468365, 0.44052017])) / 80
        # apply random position
        self.hole_translation.setSFVec3f([hole_new_position[0], 2, hole_new_position[2]])
        self.hole_rotation.setSFRotation([hole_new_rotation[0], hole_new_rotation[1], hole_new_rotation[2], hole_new_rotation[3]])


        '''reset signals'''
        self.timer = 0

        "Initial Position of the robot"
        # x/y/z in meters relative to world frame
        self.x = self.initPosition[0] - self.armPosition[0]
        self.y = -(self.initPosition[2] - self.armPosition[2])
        self.z = self.initPosition[1] - self.armPosition[1]
        # alpha/beta/gamma in rad relative to initial orientation
        self.alpha = 0.0
        self.beta = 0.0
        self.gamma = 0.0

        # Call "ikpy" to compute the inverse kinematics of the arm.
        # ikpy only compute position
        ikResults = armChain.inverse_kinematics([
            [1, 0, 0, self.x],
            [0, 1, 0, self.y],
            [0, 0, 1, self.z],
            [0, 0, 0, 1]])

        # Actuate the 3 first arm motors with the IK results.
        for i in range(3):
            self.motors[i].setPosition(ikResults[i + 1])
        self.motors[3].setPosition(self.alpha)
        self.motors[4].setPosition(-ikResults[2] - ikResults[3] + self.beta)
        self.motors[5].setPosition(self.gamma)
        for i in range(6):
            self.motors[i].setVelocity(1.0)

        """wait for robot to move to initial place"""
        for i in range (20):
            self.supervisor.step(self.timeStep)

        for i in range(6):
            self.motors[i].setVelocity(0.07)

        '''state'''
        # get
        uncode_init_state, self.init_state, = self.__get_state()

        print('initial state:')
        print("State 0-3", self.init_state[0:3])
        print("State 3-6", self.init_state[3:6])
        print("State 6-9", self.init_state[6:9])
        print("State 9-12", self.init_state[9:12])
        done = False

        # reset simulation
        self.supervisor.simulationResetPhysics()
        # TODO reset failure detection

        return self.init_state, uncode_init_state, done

    def __get_state(self):

        self.FZ = self.fz_sensor.getForceFeedback()
        self.FX = self.fx_sensor.getForceFeedback()
        self.FY = self.fy_sensor.getForceFeedback()
        self.TX = self.tx_sensor.getTorqueFeedback()
        self.TY = self.ty_sensor.getTorqueFeedback()
        self.TZ = -self.tz_sensor.getTorqueFeedback()
        currentPosition = []
        currentPosition.append(self.targetPosition[0] - (self.x + self.armPosition[0]))
        currentPosition.append(self.targetPosition[2] - (self.armPosition[2] - self.y))
        currentPosition.append(self.targetPosition[1] - (self.z + self.armPosition[1] - 0.14))
        # state
        state = np.concatenate((currentPosition, [self.alpha, self.beta, self.gamma],
                                [self.FX, self.FY, self.FZ], [self.TX, self.TY, self.TZ]))
        code_state = cal.code_state(state)

        return state, code_state

    def __execute_action(self, action):
        """ execute action """
        # do action
        self.x += action[0]
        self.y += action[1]
        self.z -= action[2]
        self.alpha += action[3]
        self.beta += action[4]
        self.gamma -= action[5]

        # bound position
        self.x = np.clip(self.x, self.initPosition[0] - self.armPosition[0] - 0.02, self.initPosition[0] - self.armPosition[0] + 0.02)
        self.y = np.clip(self.y, self.armPosition[2] - self.initPosition[2] - 0.02, self.armPosition[2] - self.initPosition[2] + 0.02)
        self.z = np.clip(self.z, self.initPosition[1] - self.armPosition[1] - 0.06, self.initPosition[1] - self.armPosition[1] + 0.04)
        self.alpha = np.clip(self.alpha, -1, 1)
        self.beta = np.clip(self.beta, -1, 1)
        self.gamma = np.clip(self.gamma, -1, 1)

        # Call "ikpy" to compute the inverse kinematics of the arm.
        # ikpy only compute position
        ikResults = armChain.inverse_kinematics([
            [1, 0, 0, self.x],
            [0, 1, 0, self.y],
            [0, 0, 1, self.z],
            [0, 0, 0, 1]])

        # Actuate the 3 first arm motors with the IK results.
        for i in range(3):
            self.motors[i].setPosition(ikResults[i + 1])
        self.motors[3].setPosition(self.alpha)
        self.motors[4].setPosition(-ikResults[2] - ikResults[3] + self.beta)
        self.motors[5].setPosition(self.gamma)

    @staticmethod
    def sample_action():
        return (np.random.rand(6) - 0.5)/10


if __name__ == '__main__':
    env = ArmEnv()
    count = 0
    file_name = 'Double_rand_f0.5_s1.5_'
    for j in range(10):
        # prepare to plt force and position
        time = 0
        plt_data = np.empty([13, 1])

        for i in range(200):
            a = env.sample_action()
            # env.step(a)
            s, _, r, done, _ = env.step([(0, 0, 0, 0, 0, 0), ""])
            # if done:
            #     break
            state = np.array([np.append(s, time)]).T
            if time == 0:
                plt_data = state
            else:
                plt_data = np.dstack((plt_data, state))
            time += 1
        # save all states
        np.save(file_name+str(count)+'.npy', plt_data)
        # plot position
        plt.figure()
        plt.subplot(231)
        plt.plot(plt_data[12][0], plt_data[0][0])
        plt.subplot(232)
        plt.plot(plt_data[12][0], plt_data[1][0])
        plt.subplot(233)
        plt.plot(plt_data[12][0], plt_data[2][0])
        plt.subplot(234)
        plt.plot(plt_data[12][0], plt_data[3][0])
        plt.subplot(235)
        plt.plot(plt_data[12][0], plt_data[4][0])
        plt.subplot(236)
        plt.plot(plt_data[12][0], plt_data[5][0])
        plt.savefig(file_name+'position'+str(count)+'.png')
        # plot force
        plt.figure()
        plt.subplot(231)
        plt.plot(plt_data[12][0], plt_data[6][0])
        plt.subplot(232)
        plt.plot(plt_data[12][0], plt_data[7][0])
        plt.subplot(233)
        plt.plot(plt_data[12][0], plt_data[8][0])
        plt.subplot(234)
        plt.plot(plt_data[12][0], plt_data[9][0])
        plt.subplot(235)
        plt.plot(plt_data[12][0], plt_data[10][0])
        plt.subplot(236)
        plt.plot(plt_data[12][0], plt_data[11][0])
        plt.savefig(file_name+'force'+str(count)+'.png')
        count += 1
        env.reset()
