"""Bounded, display-only PWM means and envelopes from accepted solver points.

This never supplies controller inputs or acceptance metrics. Means use linear
interpolation / time-weighted trapezoids, not point averages. All complete PWM
cycles contribute, including cycles with zero current. Missing channels remain
missing. At most max_bins stored bins plus one pending complete-cycle group are
retained; adjacent equal-duration groups are merged when storage fills.
"""
from __future__ import annotations
import math
import numpy as np
from numba import njit

CURRENT_KEYS=('i_l','i_pv','i_l2','i_pv_sense','i_l_sense')


@njit(cache=True)
def _append_points(times, values, period, ix, previous_time, previous_values,
                   area, low, high, valid, group_area, group_low, group_high,
                   group_valid, means, minima, maxima, starts, ends, counts):
    # ix: initialized, cycle index, incomplete initial cycle, full cycles,
    # stored bins, cycles per stored group, pending group cycles, group start.
    channels=len(previous_values);capacity=len(starts)
    for point in range(len(times)):
        now=times[point]
        tolerance=max(period*1e-11,abs(now)*4e-15)
        if not ix[0]:
            cycle=int(math.floor((now+tolerance)/period))
            ix[0]=1;ix[1]=cycle;ix[2]=int(abs(now-cycle*period)>tolerance)
            previous_time[0]=now
            for j in range(channels):previous_values[j]=values[point,j]
            continue
        old=previous_time[0]
        if now<old-tolerance:raise ValueError('Waveform timestamps must be nondecreasing')
        if now<=old+tolerance:
            # The last value at the same timestamp is the right-hand value.
            # It contributes no fictitious duration or area to the left side.
            previous_time[0]=max(old,now)
            for j in range(channels):previous_values[j]=values[point,j]
            continue
        left=old
        while left<now-tolerance:
            boundary=(ix[1]+1)*period
            right=min(now,boundary)
            width=right-left
            if width<0 and abs(width)<=tolerance:width=0.
            if width<0:raise ValueError('Internal PWM boundary precedes interval')
            f0=(left-old)/(now-old);f1=(right-old)/(now-old)
            for j in range(channels):
                a=previous_values[j];b=values[point,j]
                if math.isfinite(a) and math.isfinite(b):
                    va=a+(b-a)*f0;vb=a+(b-a)*f1
                    area[j]+=.5*(va+vb)*width
                    low[j]=min(low[j],va,vb);high[j]=max(high[j],va,vb)
                elif width>0:valid[j]=False
            left=right
            if right>=boundary-tolerance:
                if not ix[2]:
                    if ix[6]==0:ix[7]=ix[1]
                    ix[3]+=1;ix[6]+=1
                    for j in range(channels):
                        group_area[j]+=area[j]
                        group_low[j]=min(group_low[j],low[j]);group_high[j]=max(group_high[j],high[j])
                        group_valid[j]=group_valid[j] and valid[j]
                    if ix[6]==ix[5]:
                        n=ix[4]
                        starts[n]=ix[7]*period;ends[n]=boundary;counts[n]=ix[6]
                        for j in range(channels):
                            means[n,j]=group_area[j]/(ix[6]*period) if group_valid[j] else np.nan
                            minima[n,j]=group_low[j] if group_valid[j] else np.nan
                            maxima[n,j]=group_high[j] if group_valid[j] else np.nan
                            group_area[j]=0.;group_low[j]=np.inf;group_high[j]=-np.inf;group_valid[j]=True
                        ix[4]+=1;ix[6]=0
                        if ix[4]==capacity:
                            # Equal complete-cycle groups: averaging their means
                            # exactly preserves the integrated piecewise-linear area.
                            for k in range(capacity//2):
                                a=2*k;b=a+1
                                for j in range(channels):
                                    means[k,j]=.5*(means[a,j]+means[b,j])
                                    minima[k,j]=min(minima[a,j],minima[b,j]) if math.isfinite(means[k,j]) else np.nan
                                    maxima[k,j]=max(maxima[a,j],maxima[b,j]) if math.isfinite(means[k,j]) else np.nan
                                starts[k]=starts[a];ends[k]=ends[b];counts[k]=counts[a]+counts[b]
                            ix[4]=capacity//2;ix[5]*=2
                ix[1]+=1;ix[2]=0
                for j in range(channels):area[j]=0.;low[j]=np.inf;high[j]=-np.inf;valid[j]=True
            elif now-right<=tolerance:
                break
        previous_time[0]=now
        for j in range(channels):previous_values[j]=values[point,j]


class PWMMeanSummary:
    """Feed chronological batches before plot compaction; snapshot is JSON safe.

    add_points accepts seconds and an N x len(keys) float array. NaN represents
    an absent channel. A cycle with any positive-duration missing interval has
    mean/min/max null. Duplicate times use the last value for the next interval.
    """
    def __init__(self,period_s,keys=CURRENT_KEYS,max_bins=4000):
        if not math.isfinite(period_s) or period_s<=0:raise ValueError('Positive finite PWM period required')
        if int(max_bins)!=max_bins or max_bins<2:raise ValueError('max_bins must be an integer >=2')
        self.period=float(period_s);self.keys=tuple(keys);self.capacity=int(max_bins)//2*2
        if not self.keys or len(set(self.keys))!=len(self.keys):raise ValueError('Unique nonempty signal keys required')
        n=len(self.keys)
        self.ix=np.array([0,0,0,0,0,1,0,0],dtype=np.int64)
        self.previous_time=np.zeros(1);self.previous_values=np.full(n,np.nan)
        self.area=np.zeros(n);self.low=np.full(n,np.inf);self.high=np.full(n,-np.inf);self.valid=np.ones(n,dtype=np.bool_)
        self.group_area=np.zeros(n);self.group_low=np.full(n,np.inf);self.group_high=np.full(n,-np.inf);self.group_valid=np.ones(n,dtype=np.bool_)
        self.means=np.empty((self.capacity,n));self.minima=np.empty_like(self.means);self.maxima=np.empty_like(self.means)
        self.starts=np.empty(self.capacity);self.ends=np.empty(self.capacity);self.counts=np.empty(self.capacity,dtype=np.int64)
        self.first_time=None

    def add_points(self,t_seconds,values):
        t=np.asarray(t_seconds,dtype=np.float64);v=np.asarray(values,dtype=np.float64)
        if t.ndim!=1 or v.shape!=(len(t),len(self.keys)):raise ValueError('Expected t[N] and values[N, len(keys)]')
        if not np.all(np.isfinite(t)) or np.any(t<0):raise ValueError('Finite nonnegative times required')
        if not len(t):return
        if self.first_time is None:self.first_time=float(t[0])
        _append_points(t,v,self.period,self.ix,self.previous_time,self.previous_values,
                       self.area,self.low,self.high,self.valid,self.group_area,self.group_low,self.group_high,
                       self.group_valid,self.means,self.minima,self.maxima,self.starts,self.ends,self.counts)

    def snapshot(self):
        n=int(self.ix[4]);count=int(self.ix[6]);means=self.means[:n].copy();low=self.minima[:n].copy();high=self.maxima[:n].copy()
        starts=self.starts[:n].copy();ends=self.ends[:n].copy();counts=self.counts[:n].copy()
        if count:
            mean=np.where(self.group_valid,self.group_area/(count*self.period),np.nan)
            means=np.vstack((means,mean));low=np.vstack((low,np.where(self.group_valid,self.group_low,np.nan)));high=np.vstack((high,np.where(self.group_valid,self.group_high,np.nan)))
            starts=np.r_[starts,self.ix[7]*self.period];ends=np.r_[ends,(self.ix[7]+count)*self.period];counts=np.r_[counts,count]
        def clean(a):return [float(x) if math.isfinite(x) else None for x in a]
        tol=max(self.period*1e-11,abs(self.previous_time[0])*4e-15)
        initial_partial=self.first_time is not None and abs(self.first_time/self.period-round(self.first_time/self.period))*self.period>tol
        ending_partial=bool(self.ix[0] and self.previous_time[0]-self.ix[1]*self.period>tol)
        return dict(available=bool(len(counts)),period_ms=self.period*1000,
            method='pwm_cycle_time_weighted_trapezoid',source='all_accepted_points_before_plot_compaction',
            full_cycles=int(self.ix[3]),display_bins=len(counts),grouped=bool(np.any(counts>1)),
            max_cycles_per_bin=int(max(counts,default=0)),partial_cycle_omitted=bool(initial_partial or ending_partial),
            series={'t_ms':clean((starts+ends)*500),**{key:clean(means[:,j]) for j,key in enumerate(self.keys)}},
            minimum={key:clean(low[:,j]) for j,key in enumerate(self.keys)},maximum={key:clean(high[:,j]) for j,key in enumerate(self.keys)},
            cycle_counts=[int(x) for x in counts],interval_start_ms=clean(starts*1000),interval_end_ms=clean(ends*1000),
            note='表示専用。全受理点を区分線形として時間積分し完全なPWM周期で平均。複数周期の表示binでも時間平均・最小最大を保持。制御・評価指標には未使用。')


def unavailable(reason='Legacy path retained only compacted samples; exact PWM-cycle display means are not available.'):
    return dict(available=False,reason=reason,method=None,source=None)


def warmup():
    """Compile the batch kernel with synthetic zeros; not a physical test."""
    PWMMeanSummary(50e-6).add_points(np.array([0.,50e-6]),np.zeros((2,len(CURRENT_KEYS))))
