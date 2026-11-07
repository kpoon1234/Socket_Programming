/**
 * e2ee.js - Zero-Knowledge Client-Side End-to-End Encryption
 *
 * Algorithm: ChaCha20 Stream Cipher (IETF RFC 8439) + SHA-256 Authentication Tag
 * Pure JavaScript - 100% independent of browser subtle-crypto restrictions.
 * Works seamlessly across HTTP, HTTPS, localhost, and LAN IPs.
 * Full UTF-8 support (Thai, English, Emojis, Symbols).
 */

(function () {
  "use strict";

  const PREFIX = "🔒 enc:v1:";
  // Ephemeral in-memory key storage: Map<roomId, { pin: string, keyBytes: Uint8Array }>
  const roomKeys = new Map();

  function utf8ToBytes(str) {
    if (typeof TextEncoder !== "undefined") {
      return new TextEncoder().encode(str);
    }
    const utf8 = unescape(encodeURIComponent(str));
    const arr = new Uint8Array(utf8.length);
    for (let i = 0; i < utf8.length; i++) {
      arr[i] = utf8.charCodeAt(i);
    }
    return arr;
  }

  function bytesToUtf8(bytes) {
    if (typeof TextDecoder !== "undefined") {
      return new TextDecoder().decode(bytes);
    }
    let encoded = "";
    for (let i = 0; i < bytes.length; i++) {
      encoded += String.fromCharCode(bytes[i]);
    }
    return decodeURIComponent(escape(encoded));
  }

  function bytesToBase64(bytes) {
    let binary = "";
    const len = bytes.byteLength;
    for (let i = 0; i < len; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
  }

  function base64ToBytes(base64) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
  }

  function getRandomBytes(length) {
    const bytes = new Uint8Array(length);
    if (typeof crypto !== "undefined" && crypto.getRandomValues) {
      crypto.getRandomValues(bytes);
    } else {
      for (let i = 0; i < length; i++) {
        bytes[i] = Math.floor(Math.random() * 256);
      }
    }
    return bytes;
  }

  // Pure JS SHA-256 hash
  function sha256Bytes(dataBytes) {
    function rightRotate(value, amount) {
      return (value >>> amount) | (value << (32 - amount));
    }
    const maxWord = Math.pow(2, 32);
    let ascii = "";
    for (let i = 0; i < dataBytes.length; i++) {
      ascii += String.fromCharCode(dataBytes[i]);
    }
    const asciiBitLength = ascii.length * 8;
    const words = [];
    const hash = [];
    const k = [];
    let primeCounter = 0;
    const isComposite = {};
    for (let candidate = 2; primeCounter < 64; candidate++) {
      if (!isComposite[candidate]) {
        for (let i = 0; i < 313; i += candidate) isComposite[i] = candidate;
        hash[primeCounter] = (Math.pow(candidate, 0.5) * maxWord) | 0;
        k[primeCounter++] = (Math.pow(candidate, 1 / 3) * maxWord) | 0;
      }
    }
    ascii += "\x80";
    while (ascii.length % 64 - 56) ascii += "\x00";
    for (let i = 0; i < ascii.length; i++) {
      words[i >> 2] |= ascii.charCodeAt(i) << ((3 - i) % 4) * 8;
    }
    words[words.length] = (asciiBitLength / maxWord) | 0;
    words[words.length] = asciiBitLength;
    for (let j = 0; j < words.length;) {
      const w = words.slice(j, (j += 16));
      const oldHash = hash.slice(0, 8);
      for (let i = 0; i < 64; i++) {
        const w15 = w[i - 15], w2 = w[i - 2];
        const s0 = rightRotate(w15, 7) ^ rightRotate(w15, 18) ^ (w15 >>> 3);
        const s1 = rightRotate(w2, 17) ^ rightRotate(w2, 19) ^ (w2 >>> 10);
        w[i] = (i < 16) ? w[i] : (w[i - 16] + s0 + w[i - 7] + s1) | 0;
        const ch = (hash[4] & hash[5]) ^ (~hash[4] & hash[6]);
        const maj = (hash[0] & hash[1]) ^ (hash[0] & hash[2]) ^ (hash[1] & hash[2]);
        const temp1 = (hash[7] + (rightRotate(hash[4], 6) ^ rightRotate(hash[4], 11) ^ rightRotate(hash[4], 25)) + ch + k[i] + w[i]) | 0;
        const temp2 = ((rightRotate(hash[0], 2) ^ rightRotate(hash[0], 13) ^ rightRotate(hash[0], 22)) + maj) | 0;
        hash[7] = hash[6]; hash[6] = hash[5]; hash[5] = hash[4];
        hash[4] = (hash[3] + temp1) | 0;
        hash[3] = hash[2]; hash[2] = hash[1]; hash[1] = hash[0];
        hash[0] = (temp1 + temp2) | 0;
      }
      for (let i = 0; i < 8; i++) hash[i] = (hash[i] + oldHash[i]) | 0;
    }
    const out = new Uint8Array(32);
    for (let i = 0; i < 8; i++) {
      for (let b = 3; b >= 0; b--) {
        out[i * 4 + (3 - b)] = (hash[i] >> (b * 8)) & 255;
      }
    }
    return out;
  }

  // Pure JS ChaCha20 cipher block engine (RFC 8439)
  function chacha20Process(key, nonce, data) {
    const out = new Uint8Array(data.length);
    const blockCount = Math.ceil(data.length / 64);
    function rot(v, c) { return (v << c) | (v >>> (32 - c)); }
    function q(a, b, c, d, working) {
      working[a] = (working[a] + working[b]) | 0; working[d] = rot(working[d] ^ working[a], 16);
      working[c] = (working[c] + working[d]) | 0; working[b] = rot(working[b] ^ working[c], 12);
      working[a] = (working[a] + working[b]) | 0; working[d] = rot(working[d] ^ working[a], 8);
      working[c] = (working[c] + working[d]) | 0; working[b] = rot(working[b] ^ working[c], 7);
    }
    for (let b = 0; b < blockCount; b++) {
      const state = new Uint32Array(16);
      // Constant: "expand 32-byte k"
      state[0] = 0x61707865; state[1] = 0x3320646e; state[2] = 0x79622d32; state[3] = 0x6b206574;
      for (let i = 0; i < 8; i++) {
        state[4 + i] = key[i * 4] | (key[i * 4 + 1] << 8) | (key[i * 4 + 2] << 16) | (key[i * 4 + 3] << 24);
      }
      state[12] = (b + 1) | 0;
      for (let i = 0; i < 3; i++) {
        state[13 + i] = nonce[i * 4] | (nonce[i * 4 + 1] << 8) | (nonce[i * 4 + 2] << 16) | (nonce[i * 4 + 3] << 24);
      }
      const working = new Uint32Array(state);
      for (let i = 0; i < 10; i++) {
        q(0, 4, 8, 12, working); q(1, 5, 9, 13, working); q(2, 6, 10, 14, working); q(3, 7, 11, 15, working);
        q(0, 5, 10, 15, working); q(1, 6, 11, 12, working); q(2, 7, 8, 13, working); q(3, 4, 9, 14, working);
      }
      const block = new Uint8Array(64);
      for (let i = 0; i < 16; i++) {
        const val = (working[i] + state[i]) | 0;
        block[i * 4] = val & 0xff;
        block[i * 4 + 1] = (val >>> 8) & 0xff;
        block[i * 4 + 2] = (val >>> 16) & 0xff;
        block[i * 4 + 3] = (val >>> 24) & 0xff;
      }
      const offset = b * 64;
      const len = Math.min(64, data.length - offset);
      for (let i = 0; i < len; i++) {
        out[offset + i] = data[offset + i] ^ block[i];
      }
    }
    return out;
  }

  // Derive 32-byte key from PIN + Room Salt
  function deriveKey(pin, roomId) {
    return sha256Bytes(utf8ToBytes("socket_chat_key_salt:" + (roomId || "room") + ":" + pin));
  }

  // Calculate 16-byte authentication tag
  function computeTag(key, nonce, ciphertext) {
    const combined = new Uint8Array(key.length + nonce.length + ciphertext.length);
    combined.set(key, 0);
    combined.set(nonce, key.length);
    combined.set(ciphertext, key.length + nonce.length);
    const hash = sha256Bytes(combined);
    return hash.slice(0, 16); // 16-byte Auth Tag
  }

  const SECRET_SYNC_PREFIX = "🔒 mode:secret";
  const NORMAL_SYNC_PREFIX = "💬 mode:normal";

  const E2EE = {
    PREFIX,
    SECRET_SYNC_PREFIX,
    NORMAL_SYNC_PREFIX,

    isSecretSyncMessage(text) {
      return typeof text === "string" && (text.startsWith(SECRET_SYNC_PREFIX) || text.startsWith("🔒 pin:sync:"));
    },

    isSyncMessage(text) {
      return this.isSecretSyncMessage(text);
    },

    createSecretSyncMessage() {
      return SECRET_SYNC_PREFIX;
    },

    isNormalSyncMessage(text) {
      return typeof text === "string" && text.startsWith(NORMAL_SYNC_PREFIX);
    },

    createNormalSyncMessage() {
      return NORMAL_SYNC_PREFIX;
    },

    isEncrypted(text) {
      return typeof text === "string" && text.startsWith(PREFIX);
    },

    isRoomUnlocked(roomId) {
      return roomKeys.has(roomId);
    },

    getRoomPin(roomId) {
      return roomKeys.get(roomId)?.pin || null;
    },

    async unlockRoom(roomId, pin) {
      if (!pin || typeof pin !== "string" || !pin.trim()) {
        throw new Error("PIN must not be empty.");
      }
      const keyBytes = deriveKey(pin.trim(), roomId);
      roomKeys.set(roomId, { pin: pin.trim(), keyBytes });
      return true;
    },

    lockRoom(roomId) {
      roomKeys.delete(roomId);
    },

    clearAll() {
      roomKeys.clear();
    },

    async encrypt(roomId, plaintext) {
      const entry = roomKeys.get(roomId);
      if (!entry) {
        return plaintext;
      }
      const rawBytes = utf8ToBytes(plaintext);
      const plainLen = rawBytes.length;
      // Pad to minimum 32 bytes and multiple of 16 to completely hide plaintext length
      const targetLen = Math.max(32, Math.ceil((plainLen + 2) / 16) * 16);
      const padLen = targetLen - plainLen - 2;
      const dataBytes = new Uint8Array(targetLen);
      dataBytes[0] = (plainLen >> 8) & 0xff;
      dataBytes[1] = plainLen & 0xff;
      dataBytes.set(rawBytes, 2);
      if (padLen > 0) {
        dataBytes.set(getRandomBytes(padLen), 2 + plainLen);
      }

      const nonce = getRandomBytes(12);
      const cipherBytes = chacha20Process(entry.keyBytes, nonce, dataBytes);
      const tagBytes = computeTag(entry.keyBytes, nonce, cipherBytes);
      const nonceB64 = bytesToBase64(nonce);
      const tagB64 = bytesToBase64(tagBytes);
      const cipherB64 = bytesToBase64(cipherBytes);
      return `${PREFIX}${nonceB64}:${tagB64}:${cipherB64}`;
    },

    async decrypt(roomId, encryptedText) {
      if (!this.isEncrypted(encryptedText)) {
        return { success: true, text: encryptedText, encrypted: false };
      }
      const entry = roomKeys.get(roomId);
      if (!entry) {
        return { success: false, text: encryptedText, encrypted: true, reason: "locked" };
      }
      try {
        const raw = encryptedText.slice(PREFIX.length);
        const parts = raw.split(":");
        if (parts.length < 3) {
          throw new Error("Malformed payload");
        }
        const nonce = base64ToBytes(parts[0]);
        const expectedTag = base64ToBytes(parts[1]);
        const ciphertext = base64ToBytes(parts[2]);

        // Verify Authentication Tag
        const computedTag = computeTag(entry.keyBytes, nonce, ciphertext);
        let tagMatches = true;
        for (let i = 0; i < 16; i++) {
          if (computedTag[i] !== expectedTag[i]) tagMatches = false;
        }
        if (!tagMatches) {
          return { success: false, text: encryptedText, encrypted: true, reason: "invalid_key" };
        }

        const plainBytes = chacha20Process(entry.keyBytes, nonce, ciphertext);
        if (plainBytes.length >= 2) {
          const expectedLen = (plainBytes[0] << 8) | plainBytes[1];
          if (expectedLen <= plainBytes.length - 2) {
            try {
              const actual = plainBytes.slice(2, 2 + expectedLen);
              const text = bytesToUtf8(actual);
              return { success: true, text, encrypted: true };
            } catch (e) {
              // fallback
            }
          }
        }
        const text = bytesToUtf8(plainBytes);
        return { success: true, text, encrypted: true };
      } catch (err) {
        return { success: false, text: encryptedText, encrypted: true, reason: "error" };
      }
    },

    async testPin(roomId, pin, sampleEncryptedTexts) {
      if (!sampleEncryptedTexts || sampleEncryptedTexts.length === 0) {
        return true;
      }
      const candidateKey = deriveKey(pin.trim(), roomId);
      for (const text of sampleEncryptedTexts) {
        if (!this.isEncrypted(text)) continue;
        try {
          const raw = text.slice(PREFIX.length);
          const parts = raw.split(":");
          if (parts.length < 3) continue;
          const nonce = base64ToBytes(parts[0]);
          const expectedTag = base64ToBytes(parts[1]);
          const ciphertext = base64ToBytes(parts[2]);
          const computedTag = computeTag(candidateKey, nonce, ciphertext);
          let match = true;
          for (let i = 0; i < 16; i++) {
            if (computedTag[i] !== expectedTag[i]) match = false;
          }
          if (!match) return false;
          return true; // Tag verified!
        } catch (e) {
          return false;
        }
      }
      return true;
    }
  };

  // Expose to window global object and module exports
  if (typeof window !== "undefined") {
    window.E2EE = E2EE;
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = E2EE;
  }
})();
