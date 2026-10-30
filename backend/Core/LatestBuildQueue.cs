using System;
using System.Diagnostics;
using System.Threading;

namespace Lenticulizer.Core
{
    // One worker owns the raster cache. Edits replace queued work during the
    // debounce interval; running work observes cancellation between stages.
    public sealed class LatestBuildQueue<TRequest, TResult> : IDisposable where TRequest : class
    {
        readonly object gate = new object();
        readonly Func<TRequest, Func<bool>, TResult> build;
        readonly Action<TRequest, TResult, Exception> completed;
        readonly Action stopped;
        readonly Timer timer;
        readonly ManualResetEvent stopEvent = new ManualResetEvent(false);
        public bool WaitForStop(int milliseconds) { return stopEvent.WaitOne(milliseconds); }
        readonly int debounceMs;
        TRequest pending;
        long version, dueAt;
        bool running, due, disposed, stopCalled;

        public LatestBuildQueue(int debounceMs, Func<TRequest, Func<bool>, TResult> build,
            Action<TRequest, TResult, Exception> completed, Action stopped)
        {
            this.debounceMs = Math.Max(0, debounceMs);
            this.build = build;
            this.completed = completed;
            this.stopped = stopped;
            timer = new Timer(Wake, null, Timeout.Infinite, Timeout.Infinite);
        }
        public void Submit(TRequest request)
        {
            if (request == null) throw new ArgumentNullException("request");
            lock (gate)
            {
                if (disposed) throw new ObjectDisposedException("LatestBuildQueue");
                version++;
                pending = request;
                due = false;
                dueAt = Stopwatch.GetTimestamp() + (long)debounceMs * Stopwatch.Frequency / 1000;
                timer.Change(debounceMs, Timeout.Infinite);
            }
        }
        public void Cancel()
        {
            lock (gate)
            {
                if (disposed) return;
                version++;
                pending = null;
                due = false;
                timer.Change(Timeout.Infinite, Timeout.Infinite);
            }
        }
        bool Cancelled(long ticket) { lock (gate) return disposed || ticket != version; }
        void Wake(object unused)
        {
            TRequest request; long ticket;
            lock (gate)
            {
                if (disposed || pending == null) return;
                long remaining = dueAt - Stopwatch.GetTimestamp();
                if (remaining > 0) { timer.Change((int)Math.Ceiling(remaining * 1000.0 / Stopwatch.Frequency), Timeout.Infinite); return; }
                due = true;
                if (running) return;
                running = true;
                due = false;
                request = pending;
                pending = null;
                ticket = version;
            }
            TResult result = default(TResult);
            Exception error = null;
            try { result = build(request, delegate { return Cancelled(ticket); }); }
            catch (Exception e) { error = e; }
            // Never invoke client code with the queue lock held.
            try { completed(request, result, error); }
            finally
            {
                bool stop = false;
                lock (gate)
                {
                    running = false;
                    if (!disposed && due && pending != null) timer.Change(0, Timeout.Infinite);
                    if (disposed && !stopCalled) { stopCalled = true; stop = true; }
                }
                if (stop) { try { if (stopped != null) stopped(); } finally { stopEvent.Set(); } }
            }
        }
        public void Dispose()
        {
            bool stop = false;
            lock (gate)
            {
                if (disposed) return;
                disposed = true;
                version++;
                pending = null;
                timer.Dispose();
                if (!running && !stopCalled) { stopCalled = true; stop = true; }
            }
            if (stop) { try { if (stopped != null) stopped(); } finally { stopEvent.Set(); } }
        }
    }
}
