// Keycap silhouettes + position->shape map, extracted verbatim from NayaFlow's
// renderer (see docs/asset-provenance.md). Ve/Tl are the common rounded keys;
// the rest are the custom angled silhouettes that mirror the physical device.

export const SHAPES = {
  "att": {
    "viewBox": "0 0 44 54",
    "d": "M34.6409 1.18708L6.64095 6.72875C3.3625 7.37761 1 10.2535 1 13.5955V46C1 49.866 4.13401 53 8 53H36C39.866 53 43 49.866 43 46V8.05388C43 3.64228 38.9686 0.330567 34.6409 1.18708Z",
    "legend": {
      "top": "50%",
      "left": "50%"
    }
  },
  "itt": {
    "viewBox": "0 0 44 56",
    "d": "M6.98985 5.76206C3.55043 6.26364 1 9.21299 1 12.6888V47.7503C1 51.6163 4.13401 54.7503 8 54.7503H36C39.866 54.7503 43 51.6163 43 47.7503V8.60546C43 4.33739 39.2132 1.06282 34.9898 1.67873L6.98985 5.76206Z",
    "legend": {
      "top": "53%",
      "left": "50%"
    }
  },
  "rtt": {
    "viewBox": "0 0 44 59",
    "d": "M7.20313 4.9806C3.66858 5.3856 1 8.37742 1 11.9351V51C1 54.866 4.13401 58 8 58H36C39.866 58 43 54.866 43 51V8.72676C43 4.54508 39.3576 1.29623 35.2031 1.77227L7.20313 4.9806Z",
    "legend": {
      "top": "52%",
      "left": "50%"
    }
  },
  "ltt": {
    "viewBox": "0 0 45 48",
    "d": "M35.4929 1.13896L7.49289 3.18062C3.83412 3.44741 1.00195 6.4936 1.00195 10.1621V39.417C1.00195 43.283 4.13596 46.417 8.00195 46.417H36.002C39.8679 46.417 43.002 43.283 43.002 39.417V8.12042C43.002 4.05392 39.5486 0.843226 35.4929 1.13896Z",
    "legend": {
      "top": "51%",
      "left": "50%"
    }
  },
  "ctt": {
    "viewBox": "0 0 44 45",
    "d": "M35.8542 1.54481L7.8542 2.12815C4.04585 2.20749 1 5.31746 1 9.12663V36.417C1 40.283 4.13401 43.417 8 43.417H36C39.866 43.417 43 40.283 43 36.417V8.54329C43 4.62023 39.7764 1.4631 35.8542 1.54481Z",
    "legend": {
      "top": "52%",
      "left": "50%"
    }
  },
  "dtt": {
    "viewBox": "0 0 44 48",
    "d": "M8.1458 1.12782C4.22359 1.04611 1 4.20324 1 8.1263V39.75C1 43.616 4.13401 46.75 8 46.75H36C39.866 46.75 43 43.616 43 39.75V8.70963C43 4.90046 39.9541 1.79049 36.1458 1.71115L8.1458 1.12782Z",
    "legend": {
      "top": "50%",
      "left": "50%"
    }
  },
  "utt": {
    "viewBox": "0 0 45 50",
    "d": "M37.3426 2.62148L9.34261 1.16312C5.33901 0.954597 1.97852 4.14462 1.97852 8.15365V41.6664C1.97852 45.5324 5.11252 48.6664 8.97851 48.6664H36.9785C40.8445 48.6664 43.9785 45.5324 43.9785 41.6664V9.61201C43.9785 5.88751 41.0621 2.81521 37.3426 2.62148Z",
    "legend": {
      "top": "50%",
      "left": "50%"
    }
  },
  "ptt": {
    "viewBox": "0 0 45 100",
    "d": "M36.7405 4.53261L8.73013 1.61487C4.58861 1.18347 0.988484 4.44097 1.00494 8.60487L1.33194 91.3361C1.35751 97.8043 9.39085 100.78 13.6243 95.89L26.9132 80.539C27.1374 80.28 27.3877 80.0447 27.6601 79.8368L40.6217 69.9451C42.3701 68.6107 43.3898 66.5322 43.3748 64.3328L43.0151 11.4473C42.9908 7.8804 40.2883 4.90218 36.7405 4.53261Z",
    "legend": {
      "top": "45%",
      "left": "50%"
    }
  },
  "gtt": {
    "viewBox": "0 0 45 100",
    "d": "M8.25954 4.53261L36.2699 1.61487C40.4114 1.18347 44.0115 4.44097 43.9951 8.60487L43.6681 91.3361C43.6425 97.8043 35.6092 100.78 31.3757 95.89L18.0868 80.539C17.8626 80.28 17.6123 80.0447 17.3399 79.8368L4.37833 69.9451C2.62989 68.6107 1.61025 66.5322 1.62521 64.3328L1.98495 11.4473C2.00921 7.8804 4.71173 4.90218 8.25954 4.53261Z",
    "legend": {
      "top": "45%",
      "left": "50%"
    }
  },
  "ftt": {
    "viewBox": "0 0 45 50",
    "d": "M7.65739 2.62148L35.6574 1.16312C39.661 0.954597 43.0215 4.14462 43.0215 8.15365V41.6664C43.0215 45.5324 39.8875 48.6664 36.0215 48.6664H8.02148C4.15549 48.6664 1.02148 45.5324 1.02148 41.6664V9.61201C1.02148 5.88751 3.93794 2.81521 7.65739 2.62148Z",
    "legend": {
      "top": "51%",
      "left": "50%"
    }
  },
  "htt": {
    "viewBox": "0 0 44 48",
    "d": "M7.8542 1.71115L35.8542 1.12782C39.7764 1.04611 43 4.20324 43 8.1263V39.75C43 43.616 39.866 46.75 36 46.75H8C4.13401 46.75 1 43.616 1 39.75V8.70963C1 4.90046 4.04585 1.79049 7.8542 1.71115Z",
    "legend": {
      "top": "51%",
      "left": "50%"
    }
  },
  "mtt": {
    "viewBox": "0 0 44 45",
    "d": "M8.1458 1.54481L36.1458 2.12815C39.9541 2.20749 43 5.31746 43 9.12663V36.417C43 40.283 39.866 43.417 36 43.417H8C4.13401 43.417 1 40.283 1 36.417V8.54329C1 4.62023 4.22359 1.4631 8.1458 1.54481Z",
    "legend": {
      "top": "52%",
      "left": "50%"
    }
  },
  "_tt": {
    "viewBox": "0 0 45 48",
    "d": "M9.50711 1.13896L37.5071 3.18062C41.1659 3.44741 43.998 6.4936 43.998 10.1621V39.417C43.998 43.283 40.864 46.417 36.998 46.417H8.99805C5.13205 46.417 1.99805 43.283 1.99805 39.417V8.12042C1.99805 4.05392 5.45137 0.843226 9.50711 1.13896Z",
    "legend": {
      "top": "52%",
      "left": "50%"
    }
  },
  "vtt": {
    "viewBox": "0 0 44 59",
    "d": "M8.79688 1.77227L36.7969 4.9806C40.3314 5.3856 43 8.37742 43 11.9351V51C43 54.866 39.866 58 36 58H8C4.13401 58 1 54.866 1 51V8.72676C1 4.54508 4.64238 1.29623 8.79688 1.77227Z",
    "legend": {
      "top": "53%",
      "left": "50%"
    }
  },
  "xtt": {
    "viewBox": "0 0 44 56",
    "d": "M9.01015 1.67873L37.0101 5.76206C40.4496 6.26364 43 9.21299 43 12.6888V47.7503C43 51.6163 39.866 54.7503 36 54.7503H8C4.13401 54.7503 1 51.6163 1 47.7503V8.60546C1 4.33739 4.78675 1.06282 9.01015 1.67873Z",
    "legend": {
      "top": "52%",
      "left": "50%"
    }
  },
  "ytt": {
    "viewBox": "0 0 44 54",
    "d": "M9.35906 1.18708L37.3591 6.72875C40.6375 7.37761 43 10.2535 43 13.5955V46C43 49.866 39.866 53 36 53H8C4.13401 53 1 49.866 1 46V8.05388C1 3.64228 5.0314 0.330567 9.35906 1.18708Z",
    "legend": {
      "top": "55%",
      "left": "50%"
    }
  },
  "Ve": {
    "viewBox": "0 0 44 44",
    "rect": {
      "x": 1,
      "y": 1,
      "w": 42,
      "h": 42,
      "rx": 7
    },
    "legend": {
      "top": "50%",
      "left": "50%"
    }
  },
  "wtt": {
    "viewBox": "0 0 53 45",
    "d": "M40.759 1.66699H8.97852C5.11252 1.66699 1.97852 4.801 1.97852 8.66699V36.667C1.97852 40.533 5.11252 43.667 8.97851 43.667H37.2971C40.3701 43.667 43.0838 41.6627 43.9875 38.7256L51.5274 14.221C52.347 11.5574 51.5084 8.66128 49.3925 6.8476L45.3145 3.3522C44.0458 2.26474 42.43 1.66699 40.759 1.66699Z",
    "legend": {
      "top": "51%",
      "left": "45%"
    }
  },
  "Tl": {
    "viewBox": "0 0 44 58",
    "rect": {
      "x": 1,
      "y": 1,
      "w": 42,
      "h": 55.33,
      "rx": 7
    },
    "legend": {
      "top": "52%",
      "left": "50%"
    }
  },
  "btt": {
    "viewBox": "0 0 53 45",
    "d": "M12.241 1.66699H44.0215C47.8875 1.66699 51.0215 4.801 51.0215 8.66699V36.667C51.0215 40.533 47.8875 43.667 44.0215 43.667H15.7029C12.6299 43.667 9.91621 41.6627 9.01248 38.7256L1.47261 14.221C0.653023 11.5574 1.49155 8.66128 3.60752 6.8476L7.68549 3.3522C8.95419 2.26474 10.57 1.66699 12.241 1.66699Z",
    "legend": {
      "top": "50%",
      "left": "58%"
    }
  },
  "ktt": {
    "viewBox": "0 0 45 59",
    "d": "M36.9785 1.66699H8.97852C5.11252 1.66699 1.97852 4.801 1.97852 8.66699V40.0887C1.97852 42.0091 2.7675 43.8452 4.16069 45.167L15.11 55.5547C17.4573 57.7817 21.0251 58.1097 23.7391 56.348L40.7898 45.2799C42.7784 43.9891 43.9785 41.7793 43.9785 39.4085V8.66699C43.9785 4.801 40.8445 1.66699 36.9785 1.66699Z",
    "legend": {
      "top": "40%",
      "left": "50%"
    }
  },
  "Ett": {
    "viewBox": "0 0 45 59",
    "d": "M8.02148 1.66699H36.0215C39.8875 1.66699 43.0215 4.801 43.0215 8.66699V40.0887C43.0215 42.0091 42.2325 43.8452 40.8393 45.167L29.89 55.5547C27.5427 57.7817 23.9749 58.1097 21.2609 56.348L4.21019 45.2799C2.22156 43.9891 1.02148 41.7793 1.02148 39.4085V8.66699C1.02148 4.801 4.15549 1.66699 8.02148 1.66699Z",
    "legend": {
      "top": "40%",
      "left": "50%"
    }
  },
  "Ctt": {
    "viewBox": "0 0 44 50",
    "d": "M36 1.91699H8C4.13401 1.91699 1 5.05099 1 8.91699V41.8119C1 46.0799 4.78676 49.3545 9.01015 48.7386L37.0101 44.6553C40.4496 44.1537 43 41.2043 43 37.7285V8.91699C43 5.051 39.866 1.91699 36 1.91699Z",
    "legend": {
      "top": "50%",
      "left": "50%"
    }
  },
  "Stt": {
    "viewBox": "0 0 44 49",
    "d": "M36 1.08301H8C4.13401 1.08301 1 4.21701 1 8.08301V40.1445C1 44.4126 4.78676 47.6872 9.01015 47.0713L37.0101 42.9879C40.4496 42.4864 43 39.537 43 36.0612V8.08301C43 4.21701 39.866 1.08301 36 1.08301Z",
    "legend": {
      "top": "48%",
      "left": "50%"
    }
  },
  "Ttt": {
    "viewBox": "0 0 44 45",
    "d": "M36 1H8C4.13401 1 1 4.13401 1 8V36.5925C1 40.7454 4.59471 43.9851 8.72524 43.5549L36.7252 40.6382C40.2912 40.2667 43 37.2611 43 33.6759V8C43 4.13401 39.866 1 36 1Z",
    "legend": {
      "top": "47%",
      "left": "50%"
    }
  },
  "Itt": {
    "viewBox": "0 0 45 55",
    "d": "M36.002 1.41699H8.00195C4.13596 1.41699 1.00195 4.55099 1.00195 8.41699V46.8636C1.00195 50.9014 4.40872 54.1019 8.43861 53.85L36.4386 52.1C40.1278 51.8694 43.002 48.8101 43.002 45.1136V8.41699C43.002 4.551 39.8679 1.41699 36.002 1.41699Z",
    "legend": {
      "top": "49%",
      "left": "50%"
    }
  },
  "Ltt": {
    "viewBox": "0 0 112 53",
    "d": "M92.0147 1.91699H8C4.13401 1.91699 1 5.051 1 8.91699V44.3644C1 48.2542 4.17138 51.3981 8.06112 51.3641L93.4715 50.6182C96.2702 50.5937 98.7854 48.9045 99.8668 46.3231L109.7 22.8505C110.798 20.2297 110.202 17.2053 108.193 15.1961L96.9645 3.96724C95.6517 2.65449 93.8712 1.91699 92.0147 1.91699Z",
    "legend": {
      "top": "50%",
      "left": "47%"
    }
  },
  "Att": {
    "viewBox": "0 0 112 53",
    "d": "M19.9853 1.91699H104C107.866 1.91699 111 5.051 111 8.91699V44.3644C111 48.2542 107.829 51.3981 103.939 51.3641L18.5285 50.6182C15.7298 50.5937 13.2146 48.9045 12.1332 46.3231L2.3001 22.8505C1.2022 20.2297 1.7975 17.2053 3.80672 15.1961L15.0355 3.96724C16.3483 2.65449 18.1288 1.91699 19.9853 1.91699Z",
    "legend": {
      "top": "52%",
      "left": "53%"
    }
  },
  "Ott": {
    "viewBox": "0 0 45 55",
    "d": "M8.99805 1.41699H36.998C40.864 1.41699 43.998 4.55099 43.998 8.41699V46.8636C43.998 50.9014 40.5913 54.1019 36.5614 53.85L8.5614 52.1C4.87216 51.8694 1.99805 48.8101 1.99805 45.1136V8.41699C1.99805 4.551 5.13205 1.41699 8.99805 1.41699Z",
    "legend": {
      "top": "51%",
      "left": "50%"
    }
  },
  "Rtt": {
    "viewBox": "0 0 44 45",
    "d": "M8 1H36C39.866 1 43 4.13401 43 8V36.5925C43 40.7454 39.4053 43.9851 35.2748 43.5549L7.27476 40.6382C3.70884 40.2667 1 37.2611 1 33.6759V8C1 4.13401 4.13401 1 8 1Z",
    "legend": {
      "top": "50%",
      "left": "50%"
    }
  },
  "Mtt": {
    "viewBox": "0 0 44 49",
    "d": "M8 1.08301H36C39.866 1.08301 43 4.21701 43 8.08301V40.1445C43 44.4126 39.2132 47.6872 34.9899 47.0713L6.98985 42.9879C3.55043 42.4864 1 39.537 1 36.0612V8.08301C1 4.21701 4.13401 1.08301 8 1.08301Z",
    "legend": {
      "top": "48%",
      "left": "50%"
    }
  },
  "Ntt": {
    "viewBox": "0 0 44 50",
    "d": "M8 1.91699H36C39.866 1.91699 43 5.05099 43 8.91699V41.8119C43 46.0799 39.2132 49.3545 34.9899 48.7386L6.98985 44.6553C3.55043 44.1537 1 41.2043 1 37.7285V8.91699C1 5.051 4.13401 1.91699 8 1.91699Z",
    "legend": {
      "top": "50%",
      "left": "50%"
    }
  },
  "pi": {
    "viewBox": "0 0 16 244",
    "d": "M5.49267 243.582L11.8927 242.415C14.2511 241.985 16 239.457 16 236.478V14.8039C16 11.0225 13.2365 8.18367 10.269 8.91783L3.86783 10.5015C1.61976 11.0576 0 13.5226 0 16.3872V237.645C0 241.303 2.59663 244.11 5.49267 243.582Z",
    "legend": {
      "top": "50%",
      "left": "50%"
    }
  },
  "gi": {
    "viewBox": "0 0 16 244",
    "d": "M10.5073 243.582L4.10733 242.415C1.74887 241.985 0 239.457 0 236.478V14.8039C0 11.0225 2.76345 8.18367 5.73099 8.91783L12.1322 10.5015C14.3802 11.0576 16 13.5226 16 16.3872V237.645C16 241.303 13.4034 244.11 10.5073 243.582Z",
    "legend": {
      "top": "50%",
      "left": "50%"
    }
  }
};

// positionId -> shape name (index = positionId, 0..89)
export const POS_SHAPE = ["att", "itt", "rtt", "ltt", "ctt", "dtt", "utt", "ptt", "gtt", "ftt", "htt", "mtt", "_tt", "vtt", "xtt", "ytt", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "wtt", "Tl", "Tl", "btt", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "ktt", "Tl", "Tl", "Ett", "Ve", "Ve", "Ve", "Ve", "Ve", "Ve", "Ctt", "Stt", "Ttt", "Itt", "Ltt", "Tl", "Tl", "Att", "Ott", "Rtt", "Mtt", "Ntt", "pi", "pi", "pi", "pi", "pi", "pi", "pi", "pi", "gi", "gi", "gi", "gi", "gi", "gi", "gi", "gi"];

// Where a per-key badge (the multi-behaviour star) sits: the bottom-left corner of the cap's
// DRAWN silhouette, not of its box.
//
// The box is the SVG viewBox and the silhouette does not fill it. The inner-column caps (gtt,
// btt, ktt, Ett) have their bottom-left cut away, so a badge pinned to the box's corner sat
// outside the cap -- on the neighbouring key, or on the module bay beside Backspace -- and on
// the right half that corner faces the centre of the board (SCRUM-111). The owner wants the
// star where it always was, the cap's own bottom-left corner; on a cut-away cap that corner is
// simply further up the left edge. So it is computed from the path: the vertex nearest the
// box's bottom-left, stepped inward toward the cap's centroid until the glyph has half its own
// size of clearance on every side. tests/unit/starAnchor.test.js checks every shape.

// Vertices of an SVG path in absolute coordinates. Curves contribute their end points, which is
// enough for these caps: their curves are corner rounding, never a whole edge.
export function pathVertices(d) {
  const out = [];
  const toks = d.match(/[MLHVCSQTAZmlhvcsqtaz]|-?\d*\.?\d+(?:e-?\d+)?/g) || [];
  let x = 0, y = 0, cmd = "", i = 0;
  const n = () => parseFloat(toks[i++]);
  while (i < toks.length) {
    const t = toks[i];
    if (/[A-Za-z]/.test(t)) { cmd = t; i++; continue; }
    switch (cmd) {
      case "M": case "L": case "T": x = n(); y = n(); out.push([x, y]); break;
      case "m": case "l": case "t": x += n(); y += n(); out.push([x, y]); break;
      case "H": x = n(); out.push([x, y]); break;
      case "h": x += n(); out.push([x, y]); break;
      case "V": y = n(); out.push([x, y]); break;
      case "v": y += n(); out.push([x, y]); break;
      case "C": n(); n(); n(); n(); x = n(); y = n(); out.push([x, y]); break;
      case "c": n(); n(); n(); n(); x += n(); y += n(); out.push([x, y]); break;
      case "S": case "Q": n(); n(); x = n(); y = n(); out.push([x, y]); break;
      case "s": case "q": n(); n(); x += n(); y += n(); out.push([x, y]); break;
      case "A": n(); n(); n(); n(); n(); x = n(); y = n(); out.push([x, y]); break;
      case "a": n(); n(); n(); n(); n(); x += n(); y += n(); out.push([x, y]); break;
      default: i++;
    }
  }
  return out;
}

export function pointInPolygon([px, py], poly) {
  let c = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if (((yi > py) !== (yj > py)) && (px < (xj - xi) * (py - yi) / (yj - yi) + xi)) c = !c;
  }
  return c;
}

// The star is 9px on caps that render at roughly one viewBox unit per px, so half a glyph is
// the clearance it needs to sit inside a slanted edge rather than across it.
export const BADGE_CLEARANCE = 4.5;

function viewBoxSize(shape) {
  return shape.viewBox.split(" ").slice(2).map(Number);
}

function clear(p, poly, r) {
  return [[0, 0], [r, 0], [-r, 0], [0, r], [0, -r]]
    .every(([dx, dy]) => pointInPolygon([p[0] + dx, p[1] + dy], poly));
}

// The badge anchor in viewBox units, [x, y].
export function badgePoint(shape) {
  const [vw, vh] = viewBoxSize(shape);
  if (shape.rect) {
    const r = shape.rect, m = BADGE_CLEARANCE + 1;
    return [r.x + m, r.y + r.h - m];
  }
  const poly = pathVertices(shape.d);
  // The corner a person points at: the vertex furthest toward the bottom-left DIAGONALLY, the
  // polygon's support point in direction (-1, +1). "Nearest the box's corner" chose the middle
  // of gtt's long diagonal cut, and "bottom of the left edge" chose the top of btt, whose left
  // edge is short. This picks where the left edge meets the cut on gtt (4,70), where the
  // diagonal meets the bottom on btt (9,39), and the plain corner (1,91) on ptt.
  let corner = poly[0], best = -Infinity;
  for (const p of poly) {
    const score = p[1] - p[0];
    if (score > best) { best = score; corner = p; }
  }
  // Step inward up-and-right so the glyph hugs that corner, rather than toward the centroid,
  // which on a tall cut-away cap drifts it a third of the way across the key.
  const diag = Math.SQRT1_2;
  for (let s = BADGE_CLEARANCE; s <= Math.max(vw, vh); s += 0.5) {
    const p = [corner[0] + diag * s, corner[1] - diag * s];
    if (clear(p, poly, BADGE_CLEARANCE)) return p;
  }
  // Never reached for the shipped shapes; a future shape that defeats the walk gets its centre.
  const cx = poly.reduce((s, p) => s + p[0], 0) / poly.length;
  const cy = poly.reduce((s, p) => s + p[1], 0) / poly.length;
  return [cx, cy];
}

const _badge = new Map();

// CSS top/left for the badge, centred on badgePoint with translate(-50%, -50%).
export function badgeAnchor(shape) {
  if (!shape) return { top: "50%", left: "50%" };
  let a = _badge.get(shape);
  if (!a) {
    const [vw, vh] = viewBoxSize(shape);
    const [x, y] = badgePoint(shape);
    a = { left: `${(100 * x / vw).toFixed(2)}%`, top: `${(100 * y / vh).toFixed(2)}%` };
    _badge.set(shape, a);
  }
  return a;
}
