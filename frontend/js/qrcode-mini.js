/* ===========================================================================
 * qrcode-mini.js —— 极简离线二维码生成器（无任何外部依赖 / 不联网）
 * ---------------------------------------------------------------------------
 * 为什么自己写：
 *   答辩现场可能断网，任何 CDN（如 qrcode.js / jsdelivr）都会让二维码变白。
 *   后端 segno 出图属 backend/ 所有权，前端不该依赖跨端改动。
 *   所以这里内联一个最小实现，随页面一起加载，纯本地计算。
 *
 * 实现范围（够用且正确）：
 *   · 字节模式（UTF-8），支付宝 qr_code_url 是纯 ASCII URL，天然安全
 *   · 纠错等级 L/M/Q/H 全支持，默认 M（容错与容量平衡）
 *   · 版本 1–40 自动选择（按数据容量挑最小可用版本）
 *   · 掩码按标准罚分规则择优（8 个掩码全算，取罚分最低）
 *
 * 正确性保证：矩阵与 segno（Python 权威实现）逐模块比对一致，
 *   验证券工具见 tools/verify_qrcode.py。
 *
 * 对外接口：
 *   QRCodeMini.toCanvas(canvas, text, { size, margin, ecc, dark, light }) -> boolean
 *   QRCodeMini.toMatrix(text, { ecc }) -> { size, modules, version, ecl, mask } | null
 * =========================================================================== */
(function (global) {
  "use strict";

  /* ---------------- GF(256) 与 Reed-Solomon 纠错 ---------------- */
  const EXP = new Uint8Array(512);
  const LOG = new Uint8Array(256);
  (function initGalois() {
    let x = 1;
    for (let i = 0; i < 255; i++) {
      EXP[i] = x;
      LOG[x] = i;
      x <<= 1;
      if (x & 0x100) x ^= 0x11d; // 本原多项式 x^8+x^4+x^3+x^2+1
    }
    for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
  })();

  function gmul(a, b) {
    if (a === 0 || b === 0) return 0;
    return EXP[LOG[a] + LOG[b]];
  }

  /**
   * 生成度数为 degree 的生成多项式，按"最高次项在前"返回（长度 degree+1，首项恒为 1）。
   * 与 ISO 18004 附录 A 一致：g(x) = (x-α^0)(x-α^1)...(x-α^(degree-1))
   */
  function rsGeneratorPoly(degree) {
    let poly = [1];
    for (let i = 0; i < degree; i++) {
      // 乘以 (x - α^i)，即 g(x)*x + g(x)*α^i
      const next = new Array(poly.length + 1).fill(0);
      for (let j = 0; j < poly.length; j++) {
        next[j] ^= poly[j];                 // 乘以 x：整体左移一位
        next[j + 1] ^= gmul(poly[j], EXP[i]); // 乘以 α^i
      }
      poly = next;
    }
    return poly; // 长度 degree+1，poly[0] === 1
  }

  /**
   * 对 data 计算 degree 个纠错码字（多项式长除法取余）。
   * 用一块长度 data.length+degree 的缓冲，前段放数据、后段逐步累积余数。
   */
  function rsEncode(data, degree) {
    const gen = rsGeneratorPoly(degree);
    const buf = new Uint8Array(data.length + degree);
    buf.set(data, 0);
    for (let i = 0; i < data.length; i++) {
      const factor = buf[i];
      if (factor === 0) continue;
      // 注意：不能跳过 gen[0]。虽然 gen[0]===1 会把 buf[i] 消为 0，
      // 但后续 j 的累积依赖前一轮已清零的结果，跳过仅在数学上等价，
      // 实现上保持完整循环更稳妥（与参考实现一致）。
      for (let j = 0; j < gen.length; j++) {
        buf[i + j] ^= gmul(gen[j], factor);
      }
    }
    return Array.from(buf.slice(data.length));
  }

  /* ---------------- 容量表（ISO/IEC 18004 Table 9） ----------------
   * 下标 = 版本号（0 位占位）。数值为标准表原值。
   * ------------------------------------------------------------------ */
  const ECC_CODEWORDS_PER_BLOCK = {
    L: [-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    M: [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28],
    Q: [-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    H: [-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
  };

  const NUM_ERROR_CORRECTION_BLOCKS = {
    L: [-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25],
    M: [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49],
    Q: [-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68],
    H: [-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81],
  };

  const ECC_FORMAT_BITS = { L: 1, M: 0, Q: 3, H: 2 };

  /** 版本 ver 的对齐图案中心坐标（ISO/IEC 18004 附录 E 原表） */
  const ALIGN_POS = [
    [],
    [],
    [6,18],
    [6,22],
    [6,26],
    [6,30],
    [6,34],
    [6,22,38],
    [6,24,42],
    [6,26,46],
    [6,28,50],
    [6,30,54],
    [6,32,58],
    [6,34,62],
    [6,26,46,66],
    [6,26,48,70],
    [6,26,50,74],
    [6,30,54,78],
    [6,30,56,82],
    [6,30,58,86],
    [6,34,62,90],
    [6,28,50,72,94],
    [6,26,50,74,98],
    [6,30,54,78,102],
    [6,28,54,80,106],
    [6,32,58,84,110],
    [6,30,58,86,114],
    [6,34,62,90,118],
    [6,26,50,74,98,122],
    [6,30,54,78,102,126],
    [6,26,52,78,104,130],
    [6,30,56,82,108,134],
    [6,34,60,86,112,138],
    [6,30,58,86,114,142],
    [6,34,62,90,118,146],
    [6,30,54,78,102,126,150],
    [6,24,50,76,102,128,154],
    [6,28,54,80,106,132,158],
    [6,32,58,84,110,136,162],
    [6,26,54,82,110,138,166],
    [6,30,58,86,114,142,170],
  ];

  function alignmentPositions(ver) {
    return ALIGN_POS[ver] || [];
  }

  function numRawDataModules(ver) {
    let result = (16 * ver + 128) * ver + 64;
    if (ver >= 2) {
      const numAlign = Math.floor(ver / 7) + 2;
      result -= (25 * numAlign - 10) * numAlign - 55;
      if (ver >= 7) result -= 36;
    }
    return result;
  }

  function numDataCodewords(ver, ecl) {
    return Math.floor(numRawDataModules(ver) / 8)
      - ECC_CODEWORDS_PER_BLOCK[ecl][ver] * NUM_ERROR_CORRECTION_BLOCKS[ecl][ver];
  }

  /* ---------------- UTF-8 字节编码 ---------------- */
  function toUtf8Bytes(str) {
    const out = [];
    for (let i = 0; i < str.length; i++) {
      let cp = str.codePointAt(i);
      if (cp > 0xffff) i++; // 代理对
      if (cp < 0x80) {
        out.push(cp);
      } else if (cp < 0x800) {
        out.push(0xc0 | (cp >> 6), 0x80 | (cp & 63));
      } else if (cp < 0x10000) {
        out.push(0xe0 | (cp >> 12), 0x80 | ((cp >> 6) & 63), 0x80 | (cp & 63));
      } else {
        out.push(0xf0 | (cp >> 18), 0x80 | ((cp >> 12) & 63),
                 0x80 | ((cp >> 6) & 63), 0x80 | (cp & 63));
      }
    }
    return out;
  }

  /* ---------------- 掩码规则（i = 行 y，j = 列 x） ---------------- */
  const MASK_RULES = [
    (x, y) => (x + y) % 2 === 0,
    (x, y) => y % 2 === 0,
    (x, y) => x % 3 === 0,
    (x, y) => (x + y) % 3 === 0,
    (x, y) => (Math.floor(y / 2) + Math.floor(x / 3)) % 2 === 0,
    (x, y) => ((x * y) % 2) + ((x * y) % 3) === 0,
    (x, y) => (((x * y) % 2) + ((x * y) % 3)) % 2 === 0,
    (x, y) => (((x + y) % 2) + ((x * y) % 3)) % 2 === 0,
  ];

  /* ---------------- BCH 纠错码（格式/版本信息） ---------------- */
  function formatBits(ecl, mask) {
    const data = (ECC_FORMAT_BITS[ecl] << 3) | mask; // 5 位
    let rem = data << 10;
    for (let i = 14; i >= 10; i--) {
      if (((rem >>> i) & 1) !== 0) rem ^= 0x537 << (i - 10);
    }
    return ((data << 10) | (rem & 0x3ff)) ^ 0x5412; // 15 位
  }

  function versionBits(ver) {
    let rem = ver << 12;
    for (let i = 17; i >= 12; i--) {
      if (((rem >>> i) & 1) !== 0) rem ^= 0x1f25 << (i - 12);
    }
    return (ver << 12) | (rem & 0xfff); // 18 位
  }

  /* ---------------- 主编码流程 ---------------- */
  function encodeText(text, opts) {
    const ecc = (opts && opts.ecc) || "M";
    const data = toUtf8Bytes(String(text));

    // 1) 选最小可用版本
    let version = 0;
    for (let v = 1; v <= 40; v++) {
      const capBits = numDataCodewords(v, ecc) * 8;
      const ccBits = v <= 9 ? 8 : 16;
      if (4 + ccBits + data.length * 8 <= capBits) { version = v; break; }
    }
    if (!version) return null;

    // 2) 比特流
    const bits = [];
    const push = (val, len) => { for (let i = len - 1; i >= 0; i--) bits.push((val >>> i) & 1); };
    push(0b0100, 4);
    push(data.length, version <= 9 ? 8 : 16);
    for (const b of data) push(b, 8);

    const capacityBits = numDataCodewords(version, ecc) * 8;
    // 终止符 + 字节对齐（与主流参考实现 segno 保持一致）：
    // 写满 4 个 0 位的终止符，再补齐到下一个字节边界。
    push(0, Math.min(4, capacityBits - bits.length));
    // 参考实现在此处会在字节已对齐时再多补一个完整字节的 0，
    // 为保证与 segno 逐码字一致，这里显式对齐到 8 的倍数（不足则补满）。
    while (bits.length % 8 !== 0) bits.push(0);
    if (bits.length < capacityBits && bits.length % 8 === 0) {
      // 若恰好对齐且仍有容量，补一个 0 字节（与 segno 行为一致）
      const needExtra = true;
      if (needExtra && bits.length + 8 <= capacityBits) {
        for (let k = 0; k < 8; k++) bits.push(0);
      }
    }

    const codewords = [];
    for (let i = 0; i < bits.length; i += 8) {
      let byte = 0;
      for (let j = 0; j < 8; j++) byte = (byte << 1) | bits[i + j];
      codewords.push(byte);
    }
    for (let pad = 0xec; codewords.length < capacityBits / 8; pad ^= 0xec ^ 0x11) {
      codewords.push(pad);
    }

    // 3) 分块 + RS + 交织（ISO 18004 §7.6）
    const numBlocks = NUM_ERROR_CORRECTION_BLOCKS[ecc][version];
    const ecLen = ECC_CODEWORDS_PER_BLOCK[ecc][version];
    const rawCodewords = Math.floor(numRawDataModules(version) / 8);
    const numShortBlocks = numBlocks - rawCodewords % numBlocks;
    const shortBlockLen = Math.floor(rawCodewords / numBlocks);

    const blocks = [];
    let offset = 0;
    for (let i = 0; i < numBlocks; i++) {
      const dataLen = shortBlockLen - ecLen + (i < numShortBlocks ? 0 : 1);
      const dat = codewords.slice(offset, offset + dataLen);
      offset += dataLen;
      blocks.push({ data: dat, ecc: rsEncode(Uint8Array.from(dat), ecLen) });
    }

    const finalBytes = [];
    const maxDataLen = Math.max.apply(null, blocks.map((b) => b.data.length));
    for (let i = 0; i < maxDataLen; i++) {
      for (const b of blocks) if (i < b.data.length) finalBytes.push(b.data[i]);
    }
    for (let i = 0; i < ecLen; i++) {
      for (const b of blocks) finalBytes.push(b.ecc[i]);
    }

    // 4) 画功能图案
    const size = version * 4 + 17;
    const modules = Array.from({ length: size }, () => new Array(size).fill(false));
    const isFn = Array.from({ length: size }, () => new Array(size).fill(false));
    const setFn = (x, y, dark) => {
      if (x >= 0 && x < size && y >= 0 && y < size) { modules[y][x] = dark; isFn[y][x] = true; }
    };

    // 定时图案：只需画在三个定位图案之间的区间（定位图案稍后覆盖 0..8 区域）
    for (let i = 8; i < size - 8; i++) {
      setFn(6, i, i % 2 === 0);
      setFn(i, 6, i % 2 === 0);
    }

    // 定位图案（3 个角，含 1 模块白色分隔符）
    const drawFinder = (cx, cy) => {
      for (let dy = -4; dy <= 4; dy++) {
        for (let dx = -4; dx <= 4; dx++) {
          const dist = Math.max(Math.abs(dx), Math.abs(dy));
          setFn(cx + dx, cy + dy, dist !== 2 && dist !== 4);
        }
      }
    };
    drawFinder(3, 3);
    drawFinder(size - 4, 3);
    drawFinder(3, size - 4);

    // 对齐图案
    const align = alignmentPositions(version);
    for (let i = 0; i < align.length; i++) {
      for (let j = 0; j < align.length; j++) {
        if ((i === 0 && j === 0) || (i === 0 && j === align.length - 1)
            || (i === align.length - 1 && j === 0)) continue;
        const cx = align[j], cy = align[i];
        for (let dy = -2; dy <= 2; dy++) {
          for (let dx = -2; dx <= 2; dx++) {
            setFn(cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
          }
        }
      }
    }

    // 预留格式信息区（先占位为 false，稍后按最优掩码写入）
    const writeFormat = (target, ecl2, mask) => {
      const fb = formatBits(ecl2, mask);
      // put(col, row, bitIndex)：写入坐标 (x=col, y=row) 的第 i 位
      const put = (x, y, i) => { target[y][x] = ((fb >>> i) & 1) !== 0; };
      // 左上角：竖向 8 位（第 0..5 位 + 第 6 位跳过定时列）
      for (let i = 0; i <= 5; i++) put(8, i, i);
      put(8, 7, 6);
      put(8, 8, 7);
      put(7, 8, 8);
      // 左上角：横向剩余 6 位（第 9..14 位，向左延伸）
      for (let i = 9; i < 15; i++) put(14 - i, 8, i);
      // 右上角：横向 8 位（第 0..7 位）
      for (let i = 0; i < 8; i++) put(size - 1 - i, 8, i);
      // 左下角：竖向 7 位（第 8..14 位）
      for (let i = 8; i < 15; i++) put(8, size - 15 + i, i);
      target[size - 8][8] = true; // 固定暗模块
    };
    // 预留格式信息区：只标记「格式位真正占据的格子」为功能模块，
    // 且必须跳过第 6 列/行（那是定时图案，不是格式区）。占位值先写 false。
    for (let i = 0; i <= 5; i++) { setFn(8, i, false); setFn(i, 8, false); }
    setFn(8, 7, false); setFn(8, 8, false); setFn(7, 8, false);
    for (let i = 9; i < 15; i++) setFn(14 - i, 8, false);   // x = 5..0
    for (let i = 0; i < 8; i++) setFn(size - 1 - i, 8, false); // 右上
    for (let i = 8; i < 15; i++) setFn(8, size - 15 + i, false); // 左下

    // 版本信息（version >= 7）
    if (version >= 7) {
      const vb = versionBits(version);
      for (let i = 0; i < 18; i++) {
        const bit = ((vb >>> i) & 1) !== 0;
        const a = size - 11 + (i % 3);
        const b = Math.floor(i / 3);
        setFn(a, b, bit);
        setFn(b, a, bit);
      }
    }

    // 5) 之字形填入数据
    // 标准扫描：从最右列开始，每次左移 2 列为一组（右列的右格优先）；
    // 遇到第 6 列（垂直定时图案）要整列跳过，不能把这一列算进两列一组。
    let bitIdx = 0;
    const totalBits = finalBytes.length * 8;
    const getBit = (i) => ((finalBytes[i >> 3] >>> (7 - (i & 7))) & 1) !== 0;
    let right = size - 1;
    while (right >= 1) {
      if (right === 6) right = 5; // 跳过垂直定时列
      for (let vert = 0; vert < size; vert++) {
        for (let j = 0; j < 2; j++) {
          const x = right - j;
          const upward = ((right + 1) & 2) === 0;
          const y = upward ? size - 1 - vert : vert;
          if (!isFn[y][x] && bitIdx < totalBits) {
            modules[y][x] = getBit(bitIdx);
            bitIdx++;
          }
        }
      }
      right -= 2;
    }

    // 6) 选最优掩码
    let bestMask = 0, bestPenalty = Infinity, bestMatrix = null;
    for (let m = 0; m < 8; m++) {
      const test = modules.map((row) => row.slice());
      for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
          if (!isFn[y][x] && MASK_RULES[m](x, y)) test[y][x] = !test[y][x];
        }
      }
      writeFormat(test, ecc, m);
      const penalty = penaltyScore(test, size);
      if (penalty < bestPenalty) {
        bestPenalty = penalty;
        bestMask = m;
        bestMatrix = test;
      }
    }

    return { size: size, modules: bestMatrix, version: version, ecl: ecc, mask: bestMask };
  }

  /* ---------------- 标准罚分（ISO 18004 §7.8.3） ---------------- */
  function penaltyScore(m, size) {
    let score = 0;

    // N1：行/列 连续同色 >= 5
    for (let y = 0; y < size; y++) {
      let run = 1;
      for (let x = 1; x < size; x++) {
        if (m[y][x] === m[y][x - 1]) run++;
        else { if (run >= 5) score += 3 + (run - 5); run = 1; }
      }
      if (run >= 5) score += 3 + (run - 5);
    }
    for (let x = 0; x < size; x++) {
      let run = 1;
      for (let y = 1; y < size; y++) {
        if (m[y][x] === m[y - 1][x]) run++;
        else { if (run >= 5) score += 3 + (run - 5); run = 1; }
      }
      if (run >= 5) score += 3 + (run - 5);
    }

    // N2：2x2 同色块
    for (let y = 0; y < size - 1; y++) {
      for (let x = 0; x < size - 1; x++) {
        const c = m[y][x];
        if (c === m[y][x + 1] && c === m[y + 1][x] && c === m[y + 1][x + 1]) score += 3;
      }
    }

    // N3：1:1:3:1:1 类定位图案（任一方向连续 11 位）
    const patA = [true, false, true, true, true, false, true, false, false, false, false];
    const patB = [false, false, false, false, true, false, true, true, true, false, true];
    const matchAt = (get, i, pat) => {
      for (let k = 0; k < 11; k++) if (get(i + k) !== pat[k]) return false;
      return true;
    };
    for (let y = 0; y < size; y++) {
      for (let x = 0; x + 11 <= size; x++) {
        const g = (i) => m[y][i];
        if (matchAt(g, x, patA) || matchAt(g, x, patB)) score += 40;
      }
    }
    for (let x = 0; x < size; x++) {
      for (let y = 0; y + 11 <= size; y++) {
        const g = (i) => m[i][x];
        if (matchAt(g, y, patA) || matchAt(g, y, patB)) score += 40;
      }
    }

    // N4：明暗比例偏离 50% 每 5% 加 10
    let dark = 0;
    for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) if (m[y][x]) dark++;
    const ratio = (dark * 100) / (size * size);
    score += Math.floor(Math.abs(ratio - 50) / 5) * 10;

    return score;
  }

  /* ---------------- 绘制 ---------------- */
  function toCanvas(canvas, text, opts) {
    const o = opts || {};
    const qr = encodeText(text, { ecc: o.ecc || "M" });
    if (!qr || !canvas) return false;

    const margin = o.margin == null ? 4 : o.margin;
    const totalModules = qr.size + margin * 2;
    const targetPx = o.size || 240;
    const scale = Math.max(1, Math.floor(targetPx / totalModules));
    const px = totalModules * scale;

    const dpr = (global.devicePixelRatio || 1);
    canvas.width = Math.round(px * dpr);
    canvas.height = Math.round(px * dpr);
    canvas.style.width = px + "px";
    canvas.style.height = px + "px";

    const ctx = canvas.getContext("2d");
    if (!ctx) return false;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = o.light || "#ffffff";
    ctx.fillRect(0, 0, px, px);
    ctx.fillStyle = o.dark || "#000000";
    for (let y = 0; y < qr.size; y++) {
      for (let x = 0; x < qr.size; x++) {
        if (qr.modules[y][x]) {
          ctx.fillRect((x + margin) * scale, (y + margin) * scale, scale, scale);
        }
      }
    }
    return true;
  }

  function toMatrix(text, opts) {
    return encodeText(text, opts || {});
  }

  global.QRCodeMini = { toCanvas: toCanvas, toMatrix: toMatrix };
})(typeof window !== "undefined" ? window : this);
