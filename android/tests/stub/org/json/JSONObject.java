package org.json;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 极简 org.json 替身（仅供 RT1110 端到端测试使用）。
 *
 * 为什么需要：android.jar 里的 org.json 全是 `throw new RuntimeException("Stub!")` 的桩，
 * 而 RT1110 要在 PC 上直接跑**真实** FlashNode 类来抓包定位「电脑发文字安卓收不到」。
 * 这里只实现被测路径真正用到的方法，不追求完整语义。
 *
 * 放在测试 classpath 的最前面（classpath 顺序早于 android.jar）即可生效。
 */
public class JSONObject {

    private final Map<String, Object> map = new LinkedHashMap<>();

    public JSONObject() {}

    public JSONObject(String s) {
        parse(s);
    }

    // ---------- 解析（够用的极简 JSON 解析器） ----------
    private void parse(String s) {
        if (s == null) return;
        int i = 0;
        int n = s.length();
        // 跳过前导空白
        while (i < n && Character.isWhitespace(s.charAt(i))) i++;
        if (i >= n || s.charAt(i) != '{') return;
        i++;
        while (i < n) {
            while (i < n && (Character.isWhitespace(s.charAt(i)) || s.charAt(i) == ',')) i++;
            if (i >= n || s.charAt(i) == '}') break;
            if (s.charAt(i) != '"') break;
            StringBuilder key = new StringBuilder();
            i = readString(s, i, key);
            while (i < n && (Character.isWhitespace(s.charAt(i)) || s.charAt(i) == ':')) i++;
            Object val;
            if (i < n && s.charAt(i) == '{') {
                JSONObject sub = new JSONObject();
                // 递归：借 parse 处理嵌套对象
                int depth = 0; int st = i;
                boolean inStr = false; char q = 0;
                for (; i < n; i++) {
                    char c = s.charAt(i);
                    if (inStr) { if (c == q && s.charAt(i - 1) != '\\') inStr = false; continue; }
                    if (c == '"' || c == '\'') { inStr = true; q = c; continue; }
                    if (c == '{') depth++;
                    else if (c == '}') { depth--; if (depth == 0) { i++; break; } }
                }
                String inner = s.substring(st, i);
                JSONObject parsed = new JSONObject();
                parsed.parse(inner);
                val = parsed;
            } else if (i < n && s.charAt(i) == '[') {
                JSONArray arr = new JSONArray();
                int st = i; int depth = 0; boolean inStr = false; char q = 0;
                for (; i < n; i++) {
                    char c = s.charAt(i);
                    if (inStr) { if (c == q && s.charAt(i - 1) != '\\') inStr = false; continue; }
                    if (c == '"' || c == '\'') { inStr = true; q = c; continue; }
                    if (c == '[') depth++;
                    else if (c == ']') { depth--; if (depth == 0) { i++; break; } }
                }
                arr.parse(s.substring(st, i));
                val = arr;
            } else if (i < n && (s.charAt(i) == '"' || s.charAt(i) == '\'')) {
                StringBuilder sb = new StringBuilder();
                i = readString(s, i, sb);
                val = sb.toString();
            } else {
                StringBuilder sb = new StringBuilder();
                while (i < n && s.charAt(i) != ',' && s.charAt(i) != '}' && !Character.isWhitespace(s.charAt(i))) {
                    sb.append(s.charAt(i)); i++;
                }
                String raw = sb.toString();
                if (raw.equals("true")) val = Boolean.TRUE;
                else if (raw.equals("false")) val = Boolean.FALSE;
                else if (raw.equals("null")) val = JSONObject.NULL;
                else {
                    try { val = Long.parseLong(raw); } catch (Exception e) {
                        try { val = Double.parseDouble(raw); } catch (Exception e2) { val = raw; }
                    }
                }
            }
            map.put(key.toString(), val);
        }
    }

    private int readString(String s, int i, StringBuilder out) {
        char q = s.charAt(i); i++;
        while (i < s.length()) {
            char c = s.charAt(i);
            if (c == '\\' && i + 1 < s.length()) {
                char nx = s.charAt(i + 1);
                switch (nx) {
                    case 'n': out.append('\n'); break;
                    case 'r': out.append('\r'); break;
                    case 't': out.append('\t'); break;
                    case 'b': out.append('\b'); break;
                    case 'f': out.append('\f'); break;
                    case 'u':
                        if (i + 5 < s.length()) {
                            out.append((char) Integer.parseInt(s.substring(i + 2, i + 6), 16));
                            i += 4;
                        }
                        break;
                    default: out.append(nx);
                }
                i += 2;
                continue;
            }
            if (c == q) return i + 1;
            out.append(c);
            i++;
        }
        return i;
    }

    // ---------- 写入 ----------
    public JSONObject put(String k, Object v) { map.put(k, v); return this; }
    public JSONObject put(String k, int v) { map.put(k, v); return this; }
    public JSONObject put(String k, long v) { map.put(k, v); return this; }
    public JSONObject put(String k, double v) { map.put(k, v); return this; }
    public JSONObject put(String k, boolean v) { map.put(k, v); return this; }

    // ---------- 读取 ----------
    public Object opt(String k) { return map.get(k); }
    public Object get(String k) { return map.get(k); }
    public boolean has(String k) { return map.containsKey(k); }
    public java.util.Iterator<String> keys() { return map.keySet().iterator(); }
    public int length() { return map.size(); }

    public String optString(String k) { return optString(k, ""); }
    public String optString(String k, String d) {
        Object v = map.get(k);
        if (v == null || v == NULL) return d;
        return String.valueOf(v);
    }
    public String getString(String k) { return optString(k, ""); }

    public int optInt(String k) { return optInt(k, 0); }
    public int optInt(String k, int d) {
        Object v = map.get(k);
        if (v instanceof Number) return ((Number) v).intValue();
        if (v instanceof String) { try { return Integer.parseInt((String) v); } catch (Exception e) { return d; } }
        return d;
    }
    public int getInt(String k) { return optInt(k, 0); }

    public long optLong(String k) { return optLong(k, 0L); }
    public long optLong(String k, long d) {
        Object v = map.get(k);
        if (v instanceof Number) return ((Number) v).longValue();
        if (v instanceof String) { try { return Long.parseLong((String) v); } catch (Exception e) { return d; } }
        return d;
    }
    public long getLong(String k) { return optLong(k, 0L); }

    public double optDouble(String k) { return optDouble(k, 0d); }
    public double optDouble(String k, double d) {
        Object v = map.get(k);
        if (v instanceof Number) return ((Number) v).doubleValue();
        return d;
    }

    public boolean optBoolean(String k) { return optBoolean(k, false); }
    public boolean optBoolean(String k, boolean d) {
        Object v = map.get(k);
        if (v instanceof Boolean) return (Boolean) v;
        if (v instanceof String) return Boolean.parseBoolean((String) v);
        return d;
    }
    public boolean getBoolean(String k) { return optBoolean(k, false); }

    public JSONObject optJSONObject(String k) {
        Object v = map.get(k);
        return v instanceof JSONObject ? (JSONObject) v : null;
    }
    public JSONObject getJSONObject(String k) { return optJSONObject(k); }

    public JSONArray optJSONArray(String k) {
        Object v = map.get(k);
        return v instanceof JSONArray ? (JSONArray) v : null;
    }
    public JSONArray getJSONArray(String k) { return optJSONArray(k); }

    @Override public String toString() {
        StringBuilder sb = new StringBuilder("{");
        boolean first = true;
        for (Map.Entry<String, Object> e : map.entrySet()) {
            if (!first) sb.append(',');
            first = false;
            sb.append('"').append(e.getKey()).append("\":");
            Object v = e.getValue();
            if (v instanceof String) sb.append('"').append(escape((String) v)).append('"');
            else if (v == NULL) sb.append("null");
            else if (v instanceof JSONObject || v instanceof JSONArray) sb.append(v.toString());
            else sb.append(v);
        }
        return sb.append('}').toString();
    }
    private static String escape(String s) {
        StringBuilder sb = new StringBuilder();
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
            }
        }
        return sb.toString();
    }

    public static final Object NULL = new Object() {
        @Override public boolean equals(Object o) { return o == this || o == null; }
        @Override public int hashCode() { return 0; }
        @Override public String toString() { return "null"; }
    };
}
