from stratum import settings

import stratum.logger
log = stratum.logger.get_logger('BasicShareLimiter')


''' This is just a cusomized ring buffer '''
class SpeedBuffer:
	def __init__(self,size_max):
		self.max = size_max
		self.data = []
		self.cur = 0
	def append(self,x):
		self.data.append(x)
		self.cur += 1
		if len(self.data) == self.max:
			self.cur=0
			self.__class__ = SpeedBufferFull
	def avg(self):
		return sum(self.data)/self.cur
	def pos(self):
		return self.cur
	def clear(self):
		self.data=[]
		self.cur=0
	def size(self):
		return self.cur

class SpeedBufferFull:
	def __init__(self,n):
		raise "you should use SpeedBuffer"
	def append(self,x):		
		self.data[self.cur]=x
		self.cur=(self.cur+1) % self.max
	def avg(self):
		return sum(self.data)/self.max
	def pos(self):
		return self.cur
	def clear(self):
		self.data=[]
		self.cur=0
		self.__class__ = SpeedBuffer
	def size(self):
		return self.max

class BasicShareLimiter(object):
    def __init__(self):
	self.worker_stats = {}
	self.target = settings.VDIFF_TARGET
	self.retarget = settings.VDIFF_RETARGET
	self.variance = self.target * (float(settings.VDIFF_VARIANCE_PERCENT)/float(100))
	self.tmin = self.target - self.variance
	self.tmax = self.target + self.variance
	self.buffersize = self.retarget / self.target *4
	# TODO: trim the hash of inactive workers

    def submit(self, connection_ref, job_id, current_difficulty, timestamp, worker_name):
	ts = int(timestamp)

	# Init the stats for this worker if it isn't set.	
	if worker_name not in self.worker_stats :
	    self.worker_stats[worker_name] = {'last_rtc': (ts - self.retarget/2), 'last_ts': ts, 'buffer': SpeedBuffer(self.buffersize) }
	    return
	
	# Standard share update of data
	self.worker_stats[worker_name]['buffer'].append(ts - self.worker_stats[worker_name]['last_ts'])
	self.worker_stats[worker_name]['last_ts'] = ts

	# Do We retarget? If not, we're done.
	if ts - self.worker_stats[worker_name]['last_rtc'] < self.retarget and self.worker_stats[worker_name]['buffer'].size() > 0:
	    return

	# Set up and log our check
	self.worker_stats[worker_name]['last_rtc'] = ts
	avg = self.worker_stats[worker_name]['buffer'].avg()
	log.info("Checking Retarget for %s avg. %i target %i+-%i" % (worker_name,avg,self.target,self.variance) )
	if avg < 1:
	    log.info("Reseting avg = 1 since it's SOOO low")
	    avg = 1

	# Figure out our Delta-Diff
	ddiff = current_difficulty - (current_difficulty * (self.target / avg))
	if (avg > self.tmax and current_difficulty > settings.POOL_TARGET):
	    if ddiff > -1:
	    	ddiff = -1
	elif avg < self.tmin:
	    if ddiff < 1:
		ddiff = 1
	else:			# If we are here, then we should not be retargeting.
	    return

	# At this point we are retargeting this worker
	new_diff = current_difficulty + ddiff
	log.info("Retarget for %s %i old: %i new: %i" % (worker_name,ddiff,current_difficulty,new_diff))

	self.worker_stats[worker_name]['buffer'].clear()
        session = connection_ref().get_session()
	session['prev_diff'] = session['difficulty']
	session['prev_jobid'] = job_id
	session['difficulty'] = new_diff
	connection_ref().rpc('mining.set_difficulty', [new_diff,], is_notification=True)

