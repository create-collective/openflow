import { useEffect, useRef, useState } from "react";
import { BASE } from "./api";

// Subscribe to the backend SSE stream. Mirrors NayaFlow's renderer: one
// EventSource at /sse, named events (sse:naya-devices-stream, etc.), with
// auto-reconnect. Returns the latest parsed payload for the given event name.
export function useSSE(eventName) {
  const [data, setData] = useState(null);
  const [connected, setConnected] = useState(false);
  const esRef = useRef(null);

  useEffect(() => {
    let closed = false;
    let retry = 0;

    function connect() {
      const es = new EventSource(`${BASE}/sse`);
      esRef.current = es;

      es.onopen = () => {
        retry = 0;
        setConnected(true);
      };
      es.onerror = () => {
        setConnected(false);
        es.close();
        if (!closed && retry < 20) {
          retry += 1;
          setTimeout(connect, 3000);
        }
      };
      es.addEventListener(eventName, (e) => {
        try {
          setData(JSON.parse(e.data));
        } catch {
          setData(e.data);
        }
      });
    }

    connect();
    return () => {
      closed = true;
      if (esRef.current) esRef.current.close();
    };
  }, [eventName]);

  return { data, connected };
}
