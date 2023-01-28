from time import time, sleep


class SlidingWindow:
    #def __init__(self, capacity, time_unit, forward_callback, drop_callback):
    def __init__(self, capacity: int, time_unit: float):
        self.capacity: int = capacity
        self.time_unit: float = time_unit
        # self.forward_callback = forward_callback
        # self.drop_callback = drop_callback
        self.cur_time = time()
        self.pre_count: int = capacity
        self.cur_count: int = 0


    #def handle(self, packet):
    def ok_to_send(self):
        if (time() - self.cur_time) > self.time_unit:
            self.cur_time = time()
            self.pre_count = self.cur_count
            self.cur_count = 0

        ec = (self.pre_count * (self.time_unit - (time() - self.cur_time)) / self.time_unit) + self.cur_count

        if (ec > self.capacity):
            # return self.drop_callback(packet)
            return False

        self.cur_count += 1
        # return self.forward_callback(packet)
        return True