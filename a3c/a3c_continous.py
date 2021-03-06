import multiprocessing
import os
import time

import gym
import numpy as np
import tensorflow as tf
import tensorlayer as tl
from RLToolbox.toolbox.common.utils import *
from RLToolbox.agent.A3C_agent import A3CAgent
from RLToolbox.storage.storage_continous_parallel import ParallelStorage
from RLToolbox.toolbox.baseline.baseline_zeros import Baseline
from RLToolbox.toolbox.distribution.diagonal_gaussian import DiagonalGaussian
from RLToolbox.environment.gym_environment import Environment

from parameters import PMS_base


class NetworkTLAction(object):
    def __init__(self, scope):
        with tf.variable_scope("%s_shared" % scope):
            self.states = tf.placeholder(
                tf.float32 , shape=[None] + pms.obs_shape , name="%s_obs" % scope)
            self.action_n = tf.placeholder(tf.float32 , shape=[None , pms.action_shape] , name="%s_action" % scope)
            self.advant = tf.placeholder(tf.float32 , shape=[None] , name="%s_advant" % scope)

            network = tl.layers.InputLayer(self.states , name='%s_input_layer'%scope)
            network = tl.layers.DenseLayer(network , n_units=64 ,
                                           act=tf.nn.relu , name="%s_fc1"%scope)
            network = tl.layers.DenseLayer(network , n_units=64 ,
                                           act=tf.nn.relu , name="%s_fc2"%scope)
            network = tl.layers.DenseLayer(network , n_units=pms.action_shape,
                                           name="%s_fc3"%scope)
            self.action_dist_means_n = network.outputs

            self.action_dist_logstd_param = tf.Variable(
                (.01 * np.random.randn(1 , pms.action_shape)).astype(np.float32) , name="%spolicy_logstd" % scope)
            # self.action_dist_logstd_param = tf.maximum(self.action_dist_logstd_param, np.log(pms.min_std))
            self.action_dist_logstds_n = tf.tile(self.action_dist_logstd_param ,
                                                 tf.pack((tf.shape(self.action_dist_means_n)[0] , 1)))
            self.var_list = [v for v in tf.trainable_variables() if v.name.startswith(scope)]

class NetworkTLValue(object):
    def __init__(self, scope):
        with tf.variable_scope("%s_shared" % scope):
            self.states = tf.placeholder(
                tf.float32 , shape=[None] + pms.obs_shape , name="%s_obs" % scope)

            self.R = tf.placeholder(tf.float32 , shape=[None] , name="%s_R" % scope)

            network = tl.layers.InputLayer(self.states , name='%s_input_layer'%scope)
            network = tl.layers.DenseLayer(network , n_units=64,
                                           act=tf.nn.relu , name="%s_fc1"%scope)
            # network = tl.layers.DenseLayer(network , n_units=64 ,
            #                                act=tf.nn.relu , name="%s_fc2"%scope)
            network = tl.layers.DenseLayer(network , n_units=1,name="%s_fc3"%scope)
            self.value = network.outputs
            self.var_list = [v for v in tf.trainable_variables() if v.name.startswith(scope)]



if __name__ == "__main__":
    pms = PMS_base()
    pms.train_flag = True
    pms.load_model_before_train = False
    pms.render = False
    args = pms
    if not os.path.isdir(pms.checkpoint_dir):
        os.makedirs(pms.checkpoint_dir)
    if not os.path.isdir("./log"):
        os.makedirs("./log")
    params = {"environment":Environment,
              "baseline":Baseline,
              "distribution":DiagonalGaussian,
              "storage":ParallelStorage,
              "agent":A3CAgent}

    args.max_pathlength = gym.spec(args.environment_name).timestep_limit
    learner_tasks = multiprocessing.JoinableQueue()
    learner_results = multiprocessing.Queue()
    learner_env = params["environment"]
    net = dict(action_net=NetworkTLAction("action"), value_net=NetworkTLValue("value"))
    baseline = params["baseline"]()
    distribution = params["distribution"](pms.action_shape)
    learners = []
    for i in xrange(4):
        learner = params["agent"](learner_env, session=None, baseline=baseline, storage=None, distribution=distribution, net=net, pms=pms, task_q=learner_tasks, result_q=learner_results, process_id=i)
        learners.append(learner)
    for learner in learners:
        learner.start()
    if pms.load_model_before_train:
        data = np.load(os.path.join(pms.checkpoint_dir, "model.npz"))
        theta = data["theta"]
        theta_v = data["theta_v"]
    else:
        learner_tasks.put(dict(type="GET_PARAM"))
        learner_tasks.join()
        theta, theta_v = learner_results.get()
    if pms.train_flag:
        for i in xrange(pms.max_iter_number):
            print "#############%d###########" % i
            if i % pms.save_model_times == 0 and i != 0:
                ## save model
                print "save_checkpoint"
                # learner_tasks.put(dict(type="GET_PARAM"))
                # learner_tasks.join()
                # theta, theta_v = learner_results.get()
                np.savez(os.path.join(pms.checkpoint_dir, "model.npz"), theta=theta, theta_v=theta_v)
            for k in xrange(pms.jobs):
                command = dict(type="TRAIN", action_param=theta, value_param=theta_v)
                learner_tasks.put(command)
            learner_tasks.join()
            thetas = []
            theta_vs = []
            for k in xrange(pms.jobs):
                delta_theta, delta_theta_v = learner_results.get()
                thetas.append(delta_theta)
                theta_vs.append(delta_theta_v)
            # update net
            theta += np.array(thetas).sum(axis=0)
            theta_v += np.array(theta_vs).sum(axis=0)
            # print "theta:" + str(theta)
            # print "theta_v" + str(theta_v)
            print
    else:
        for k in xrange(20):
            command = dict(type="TEST", action_param=theta, value_param=theta_v)
            learner_tasks.put(command)
            learner_tasks.join()
    for k in xrange(pms.jobs):
        command = dict(type="STOP", action_param=theta, value_param=theta_v)
        learner_tasks.put(command)
    learner_tasks.join()
    exit()
