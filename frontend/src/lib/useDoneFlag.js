import { useEffect, useRef, useState } from "react";

// A short-lived "that worked" flag for a button.
//
// Read and flash are both slow, both talk to hardware, and both used to finish in total
// silence -- the only way to know a flash had happened was to read the board back. The result
// belongs on the control that started it, because that is where the eye already is, and it has
// to clear itself: a success badge that stays forever stops meaning "just now".
//
// Shared rather than copied: this is the third caller, and a timer that is cleared on unmount
// in two places and leaked in the third is exactly the kind of difference nobody notices.
export default function useDoneFlag(ms = 5000) {
  const [done, setDone] = useState(false);
  const timer = useRef(null);

  useEffect(() => () => clearTimeout(timer.current), []);

  return [
    done,
    function mark() {
      setDone(true);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setDone(false), ms);
    },
    function clear() {
      clearTimeout(timer.current);
      setDone(false);
    },
  ];
}
