import math
import time

def length(points, loop):
    pairs = list(zip(points, points[1:]))
    if loop and len(points)>1:
        pairs.append((points[-1],points[0]))
    return sum(math.hypot(a['X']-b['X'],a['Y']-b['Y']) for a,b in pairs)

def optimize(points, loop, cancel=None, max_seconds=5.0):
    if len(points)<3:return list(points)
    def dist(a,b):return math.hypot(a['X']-b['X'],a['Y']-b['Y'])
    best=list(points); best_length=length(best,loop)
    deadline=time.monotonic()+max_seconds
    def cancelled():
        if cancel and cancel():raise InterruptedError('Route calculation cancelled.')
    hops=sorted(range(1,len(points)),key=lambda i:dist(points[0],points[i]))[:6]
    for hop in hops:
        cancelled()
        if time.monotonic()>deadline:return best
        order=[0,hop];remaining=set(range(1,len(points)))-{hop}
        while remaining:
            cancelled()
            if time.monotonic()>deadline:return best
            at=min(remaining,key=lambda i:(dist(points[order[-1]],points[i]),i))
            order.append(at);remaining.remove(at)
        for _ in range(100):
            changed=False
            for i in range(1,len(order)-1):
                cancelled()
                if time.monotonic()>deadline:
                    candidate=[points[k] for k in order]
                    return candidate if length(candidate,loop)<best_length else best
                for j in range(i+1,len(order)):
                    before=dist(points[order[i-1]],points[order[i]])
                    after=dist(points[order[i-1]],points[order[j]])
                    tail=order[j+1] if j+1<len(order) else order[0] if loop else None
                    if tail is not None:
                        before+=dist(points[order[j]],points[tail]);after+=dist(points[order[i]],points[tail])
                    if after+1e-7<before:
                        order[i:j+1]=reversed(order[i:j+1]);changed=True
            if not changed:break
        candidate=[points[i] for i in order];candidate_length=length(candidate,loop)
        if candidate_length<best_length:best,best_length=candidate,candidate_length
    return best

def best_route(points,loop,cancel=None):
    """Exact map-distance TSP up to 12 stops, heuristic beyond that."""
    if len(points)>12:return optimize(points,loop,cancel=cancel),False
    if len(points)<3:return list(points),True
    n=len(points)
    distances=[[math.hypot(a['X']-b['X'],a['Y']-b['Y']) for b in points] for a in points]
    dp={(1,0):(0.0,None)}
    for mask in range(1,1<<n,2):
        if cancel and cancel():raise InterruptedError('Route calculation cancelled.')
        for at in range(n):
            state=dp.get((mask,at))
            if state is None:continue
            for to in range(1,n):
                if mask&(1<<to):continue
                key=(mask|(1<<to),to);cost=state[0]+distances[at][to]
                if key not in dp or cost<dp[key][0]:dp[key]=(cost,at)
    mask=(1<<n)-1;at=min(range(1,n),key=lambda j:dp[(mask,j)][0]+(distances[j][0] if loop else 0))
    order=[]
    while at is not None:
        order.append(at);previous=dp[(mask,at)][1];mask^=1<<at;at=previous
    return [points[i] for i in reversed(order)],True
