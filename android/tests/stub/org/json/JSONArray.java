package org.json;

import java.util.ArrayList;
import java.util.List;

/** 极简 org.json 替身（仅 RT1110 测试用）。只实现被测路径用到的方法。 */
public class JSONArray {

    private final List<Object> list = new ArrayList<>();

    public JSONArray() {}

    /** android.jar 的 org.json 有此构造器，FlashNode.rememberSubnet 用到 */
    public JSONArray(java.util.Collection<?> c) { if (c != null) list.addAll(c); }

    /**
     * android.jar 的 org.json 有此构造器（从 JSON 文本解析）。
     * ★ Prefs.knownSubnets() / knownPeers() 用它读回落盘的 JSON 数组，
     *   缺了它整个 Prefs 类编译不过 —— v1.18.15 的离线队列测试需要。
     */
    public JSONArray(String s) { parse(s); }

    void parse(String s) {
        if (s == null) return;
        String inner = s.trim();
        if (inner.startsWith("[")) inner = inner.substring(1);
        if (inner.endsWith("]")) inner = inner.substring(0, inner.length() - 1);
        if (inner.trim().isEmpty()) return;
        // 简单按顶层逗号切分
        int depth = 0; boolean inStr = false; char q = 0;
        StringBuilder cur = new StringBuilder();
        for (int i = 0; i < inner.length(); i++) {
            char c = inner.charAt(i);
            if (inStr) {
                cur.append(c);
                if (c == q && inner.charAt(i - 1) != '\\') inStr = false;
                continue;
            }
            if (c == '"' || c == '\'') { inStr = true; q = c; cur.append(c); continue; }
            if (c == '{' || c == '[') depth++;
            if (c == '}' || c == ']') depth--;
            if (c == ',' && depth == 0) {
                addToken(cur.toString());
                cur.setLength(0);
                continue;
            }
            cur.append(c);
        }
        addToken(cur.toString());
    }

    private void addToken(String tok) {
        String t = tok.trim();
        if (t.isEmpty()) return;
        if (t.startsWith("{")) list.add(new JSONObject(t));
        else if (t.startsWith("[")) { JSONArray a = new JSONArray(); a.parse(t); list.add(a); }
        else if (t.startsWith("\"") || t.startsWith("'")) list.add(unquote(t));
        else if (t.equals("true")) list.add(Boolean.TRUE);
        else if (t.equals("false")) list.add(Boolean.FALSE);
        else if (t.equals("null")) list.add(JSONObject.NULL);
        else {
            try { list.add(Long.parseLong(t)); } catch (Exception e) {
                try { list.add(Double.parseDouble(t)); } catch (Exception e2) { list.add(t); }
            }
        }
    }
    private static String unquote(String t) {
        String s = t;
        if (s.length() >= 2 && (s.charAt(0) == '"' || s.charAt(0) == '\'')) s = s.substring(1);
        if (s.length() >= 1 && (s.charAt(s.length() - 1) == '"' || s.charAt(s.length() - 1) == '\''))
            s = s.substring(0, s.length() - 1);
        return s.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t")
                .replace("\\\"", "\"").replace("\\\\", "\\");
    }

    public JSONArray put(Object v) { list.add(v); return this; }
    public JSONArray put(int v) { list.add((long) v); return this; }

    /** android.jar 的 org.json 有此方法；FlashNode 限长 peers.ips 时用到 */
    public JSONArray remove(int i) {
        if (i >= 0 && i < list.size()) list.remove(i);
        return this;
    }
    public JSONArray put(long v) { list.add(v); return this; }
    public JSONArray put(double v) { list.add(v); return this; }
    public JSONArray put(boolean v) { list.add(v); return this; }

    public int length() { return list.size(); }
    public Object opt(int i) { return (i >= 0 && i < list.size()) ? list.get(i) : null; }
    public Object get(int i) { return opt(i); }
    public String optString(int i) { return optString(i, ""); }
    public String optString(int i, String d) {
        Object v = opt(i);
        if (v == null || v == JSONObject.NULL) return d;
        return String.valueOf(v);
    }
    public String getString(int i) { return optString(i, ""); }
    public int optInt(int i) { return optInt(i, 0); }
    public int optInt(int i, int d) {
        Object v = opt(i);
        if (v instanceof Number) return ((Number) v).intValue();
        return d;
    }
    public int getInt(int i) { return optInt(i, 0); }
    public long optLong(int i) { return optLong(i, 0L); }
    public long optLong(int i, long d) {
        Object v = opt(i);
        if (v instanceof Number) return ((Number) v).longValue();
        return d;
    }
    public long getLong(int i) { return optLong(i, 0L); }
    public double optDouble(int i) { return optDouble(i, 0d); }
    public double optDouble(int i, double d) {
        Object v = opt(i);
        if (v instanceof Number) return ((Number) v).doubleValue();
        return d;
    }
    public boolean optBoolean(int i) { return optBoolean(i, false); }
    public boolean optBoolean(int i, boolean d) {
        Object v = opt(i);
        if (v instanceof Boolean) return (Boolean) v;
        return d;
    }
    public boolean getBoolean(int i) { return optBoolean(i, false); }
    public JSONObject optJSONObject(int i) {
        Object v = opt(i);
        return v instanceof JSONObject ? (JSONObject) v : null;
    }
    public JSONObject getJSONObject(int i) { return optJSONObject(i); }
    public JSONArray optJSONArray(int i) {
        Object v = opt(i);
        return v instanceof JSONArray ? (JSONArray) v : null;
    }
    public JSONArray getJSONArray(int i) { return optJSONArray(i); }

    @Override public String toString() {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < list.size(); i++) {
            if (i > 0) sb.append(',');
            Object v = list.get(i);
            if (v instanceof String) sb.append('"').append(v).append('"');
            else if (v == JSONObject.NULL) sb.append("null");
            else sb.append(v);
        }
        return sb.append(']').toString();
    }
}
