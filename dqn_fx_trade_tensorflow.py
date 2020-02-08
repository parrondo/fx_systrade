# coding:utf-8
# [0]必要なライブラリのインポート

# this code based on code on https://qiita.com/sugulu/items/bc7c70e6658f204f85f9
# I am very grateful to work of Mr. Yutaro Ogawa (id: sugulu)

import numpy as np
import time
from keras.models import Sequential, model_from_json, Model
from keras.layers import Dense, BatchNormalization, Dropout
from keras.optimizers import Adam
from keras.utils import plot_model
from collections import deque
from keras import backend as K
import tensorflow as tf
import pickle
from agent_fx_environment import FXEnvironment
import os
import sys
import math

# [1]損失関数の定義
# 損失関数にhuber関数を使用 参考https://github.com/jaara/AI-blog/blob/master/CartPole-DQN.py
def huberloss(y_true, y_pred):
   err = y_true - y_pred
   cond = K.abs(err) < 1.0
   L2 = 0.5 * K.square(err)
   L1 = (K.abs(err) - 0.5)
   loss = tf.where(cond, L2, L1)  # Keras does not cover where function in tensorflow :-(
   return K.mean(loss)

# [2]Q関数をディープラーニングのネットワークをクラスとして定義
class QNetwork:
    def __init__(self, learning_rate=0.001, state_size=15, action_size=3, hidden_size=10):
        self.model = Sequential()
        self.model.add(Dense(hidden_size, activation='relu', input_dim=state_size))
        self.model.add(Dense(hidden_size, activation='relu'))
        # self.model.add(BatchNormalization())
        # self.model.add(Dropout(0.5))
        # self.model.add(Dense(hidden_size, activation='relu'))
        self.model.add(Dense(action_size, activation='linear'))

        self.optimizer = Adam(lr=learning_rate)  # 誤差を減らす学習方法はAdam
        self.model.compile(loss=huberloss,
                           optimizer=self.optimizer)


    # 重みの学習
    def replay(self, memory, batch_size, gamma):
        inputs = np.zeros((batch_size, feature_num))
        targets = np.zeros((batch_size, 3))
        mini_batch = memory.sample(batch_size)
        #mini_batch = memory.get_last(batch_size)

        for i, (state_b, action_b, reward_b, next_state_b) in enumerate(mini_batch):
            inputs[i] = state_b

            retmainQs = self.model.predict(next_state_b)[0]
            # print(retmainQs)
            next_action = np.argmax(retmainQs)  # 最大の報酬を返す行動を選択する
            target = reward_b + gamma * retmainQs[next_action]

            targets[i] = self.model.predict(state_b)    # Qネットワークの出力
            targets[i][action_b] = target               # 教師信号

        self.model.fit(inputs, targets, epochs=5, verbose=1)  # epochsは訓練データの反復回数、verbose=0は表示なしの設定

    def save_model(self, file_path_prefix_str):
        with open("./" + file_path_prefix_str + "_nw.json", "w") as f:
            f.write(self.model.to_json())
        self.model.save_weights("./" + file_path_prefix_str + "_weights.hd5")

    def load_model(self, file_path_prefix_str):
        with open("./" + file_path_prefix_str + "_nw.json", "r") as f:
            self.model = model_from_json(f.read())
        self.model.compile(loss=huberloss, optimizer=self.optimizer)
        self.model.load_weights("./" + file_path_prefix_str + "_weights.hd5")

# [3]Experience ReplayとFixed Target Q-Networkを実現するメモリクラス
class Memory:
    def __init__(self, max_size=1000):
        self.buffer = deque(maxlen=max_size)

    def add(self, experience):
        self.buffer.append(experience)

    def sample(self, batch_size):
        idx = np.random.choice(np.arange(len(self.buffer)), size=batch_size, replace=False)
        return [self.buffer[ii] for ii in idx]

    def get_last(self, num):
        deque_length = len(self.buffer)
        start = deque_length - num
        end = deque_length
        return [self.buffer[ii] for ii in range(start, end)]

    def len(self):
        return len(self.buffer)

    def save_memory(self, file_path_prefix_str):
        with open("./" + file_path_prefix_str + ".pickle", 'wb') as f:
            pickle.dump(self.buffer, f)

    def load_memory(self, file_path_prefix_str):
        with open("./" + file_path_prefix_str + ".pickle", 'rb') as f:
            self.buffer = pickle.load(f)

# [4]カートの状態に応じて、行動を決定するクラス
class Actor:
    def get_action(self, state, episode, mainQN, isBacktest = False):   # [C]ｔ＋１での行動を返す
        # 徐々に最適行動のみをとる、ε-greedy法
        epsilon = 0.001 + 0.9 / (1.0+(episode/(iteration_num * 100)))

        if epsilon <= np.random.uniform(0, 1) or isBacktest == True:
            retTargetQs = mainQN.model.predict(state)[0]
            print(retTargetQs)
            action = np.argmax(retTargetQs)  # 最大の報酬を返す行動を選択する
        else:
            action = np.random.choice([0, 1, 2])  # ランダムに行動する

        return action

# [5] メイン関数開始----------------------------------------------------
# [5.1] 初期設定--------------------------------------------------------
TRAIN_DATA_NUM = 223954 # 3years (test is 5 years)
# ---
gamma = 0.3 #0.99  # 割引係数
hidden_size = 50 # Q-networkの隠れ層のニューロンの数
learning_rate = 0.005 #0.01 # 0.05 #0.001 #0.0001 # 0.00001         # Q-networkの学習係数
memory_size = TRAIN_DATA_NUM * 2 #10000  # バッファーメモリの大きさ
batch_size = 32 #64 # 32  # Q-networkを更新するバッチの大きさ
num_episodes = TRAIN_DATA_NUM + 10  # envがdoneを返すはずなので念のため多めに設定 #1000  # 総試行回数
iteration_num = 20 # <- 1足あたり 32 * 5 * 20 で約3000回のfitが行われる計算
feature_num = 11
nn_output_size = 3

def tarin_agent():
    env_master = FXEnvironment()

    # [5.2]Qネットワークとメモリ、Actorの生成--------------------------------------------------------
    mainQN = QNetwork(hidden_size=hidden_size, learning_rate=learning_rate, state_size=feature_num, action_size=nn_output_size)     # メインのQネットワーク
    memory = Memory(max_size=memory_size)
    memory_hash = {}
    actor = Actor()

    if os.path.exists("./mainQN_nw.json"):
        # 期間は最初からになってしまうが学習済みのモデルに追加で学習を行う
        mainQN.load_model("mainQN")
        memory.load_memory("memory")

    total_get_acton_cnt = 1

    inputs = np.zeros((batch_size, feature_num))
    targets = np.zeros((batch_size, nn_output_size))
    for cur_itr in range(iteration_num):
        env = env_master.get_env('train')
        state, reward, done, info = env.step(2)  # 1step目は適当な行動をとる ("DONOT")
        state = np.reshape(state, [1, feature_num])  # list型のstateを、1行15列の行列に変換

        for episode in range(num_episodes):  # 試行数分繰り返す
            total_get_acton_cnt += 1
            action = actor.get_action(state, total_get_acton_cnt, mainQN)  # 時刻tでの行動を決定する
            next_state, reward, done, info = env.step(action)   # 行動a_tの実行による、s_{t+1}, _R{t}を計算する
            next_state = np.reshape(state, [1, feature_num])  # list型のstateを、1行11列の行列に変換

            # closeされた場合過去の各ポジションのopenについての獲得pipsが識別子文字列とともに
            # info で返されるので、その内容で過去のエピソードのリワードを更新する
            if len(info) > 1:
                for keyval in info[1:]:
                    memory_hash[keyval[0]][2] = keyval[1]

            a_log = [state, action, reward, next_state]
            memory.add(a_log)     # メモリを更新する
            # 後からrewardを更新するためにエピソード識別子をキーにエピソードを取得可能としておく
            memory_hash[info[0]] = a_log

            state = next_state  # 状態更新

            # Qネットワークの重みを学習・更新する replay
            if (memory.len() > batch_size):
                mainQN.replay(memory, batch_size, gamma)

            # 環境が提供する期間が最後までいった場合
            if done:
                print('all training period learned.')
                break

            # モデルとメモリのスナップショットをとっておく
            if episode % 10000 == 0 and episode != 0:
                # targetQN.save_model("targetQN")
                mainQN.save_model("mainQN")
                memory.save_memory("memory")

        # 一周回したら、次の周でりようされることはないのでクリア
        memory_hash = {}

def run_backtest():
    env_master = FXEnvironment()
    env = env_master.get_env("backtest")
    num_episodes = TRAIN_DATA_NUM + 10 # envがdoneを返すはずなので念のため多めに設定 #1000  # 総試行回数

    # [5.2]Qネットワークとメモリ、Actorの生成--------------------------------------------------------
    mainQN = QNetwork(hidden_size=hidden_size, learning_rate=learning_rate)     # メインのQネットワーク
    actor = Actor()

    mainQN.load_model("mainQN")

    # BUY でスタート
    state, reward, done, info = env.step(0)
    state = np.reshape(state, [1, feature_num])
    for episode in range(num_episodes):   # 試行数分繰り返す
        action = actor.get_action(state, episode, mainQN, isBacktest = True)   # 時刻tでの行動を決定する
        state, reward, done, info = env.step(action)   # 行動a_tの実行による、s_{t+1}, _R{t}を計算する
        state = np.reshape(state, [1, feature_num])
        # 環境が提供する期間が最後までいった場合
        if done:
            print('all training period learned.')
            break

if __name__ == '__main__':
    np.random.seed(1337)  # for reproducibility
    if sys.argv[1] == "train":
        tarin_agent()
    elif sys.argv[1] == "backtest":
        run_backtest()
    else:
        print("please pass argument 'train' or 'backtest'")
