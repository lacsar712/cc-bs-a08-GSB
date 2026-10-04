import m from "mithril";

const TOKEN_KEY = "bridge_strain_token";
const USER_KEY = "bridge_strain_user";

function verdictClass(verdict, status) {
  if (verdict === "合格") return "tag pass";
  if (verdict === "越界") return "tag fail";
  return "tag wait";
}

function displayVerdict(row) {
  if (row.verdict) return row.verdict;
  if (row.status === "pending") return "待处理";
  if (row.status === "processing") return "处理中";
  return "—";
}

function fmt(value, digits = 4) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? String(parseFloat(n.toFixed(digits))) : String(value);
}

const state = {
  token: localStorage.getItem(TOKEN_KEY) || "",
  user: null,
  view: "home",
  loginForm: { username: "surveyor", password: "surv123456" },
  rows: [],
  settings: null,
  settingsForm: { sensitivity: "", rated_voltage: "" },
  convForm: { path: "voltage", span_code: "", raw_voltage: "", microstrain: "" },
  preview: null,
  previewError: "",
  conversions: [],
  error: "",
  msg: "",
  loading: false,
  timer: null,
  previewTimer: null,
};

try {
  state.user = JSON.parse(localStorage.getItem(USER_KEY) || "null");
} catch {
  state.user = null;
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const res = await fetch(path, { ...opts, headers });
  const text = await res.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

async function loadReadings() {
  if (!state.token) return;
  try {
    state.rows = await api("/api/readings");
    state.error = "";
  } catch {
    state.error = "加载列表失败，请重新登录";
  }
  m.redraw();
}

async function loadConversions() {
  if (!state.token) return;
  try {
    state.conversions = await api("/api/conversions");
  } catch {
    /* 轮询静默失败，下一轮重试 */
  }
  m.redraw();
}

async function loadSettings() {
  if (!state.token) return;
  try {
    state.settings = await api("/api/settings");
    state.settingsForm.sensitivity = String(state.settings.sensitivity);
    state.settingsForm.rated_voltage = String(state.settings.rated_voltage);
    schedulePreview();
  } catch {
    /* 忽略，轮询会再试 */
  }
  m.redraw();
}

function startPolling() {
  if (state.timer) clearInterval(state.timer);
  if (!state.token) return;
  state.timer = setInterval(() => {
    loadReadings();
    if (state.view === "convert") loadConversions();
  }, 3000);
}

function previewPayload() {
  const f = state.convForm;
  if (f.path === "voltage") {
    if (f.raw_voltage === "") return null;
    return { raw_voltage: f.raw_voltage };
  }
  if (f.microstrain === "") return null;
  return { microstrain: f.microstrain };
}

function schedulePreview() {
  if (state.previewTimer) clearTimeout(state.previewTimer);
  const payload = previewPayload();
  if (!payload) {
    state.preview = null;
    state.previewError = "";
    return;
  }
  state.previewTimer = setTimeout(async () => {
    try {
      state.preview = await api("/api/convert/preview", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      state.previewError = "";
    } catch (err) {
      // 预览失败直接展示服务端统一措辞（与正式报送、直打接口完全一致）
      state.preview = null;
      state.previewError = err.message;
    }
    m.redraw();
  }, 350);
}

const App = {
  oninit() {
    loadReadings();
    startPolling();
  },
  onremove() {
    if (state.timer) clearInterval(state.timer);
    if (state.previewTimer) clearTimeout(state.previewTimer);
  },
  view() {
    if (!state.token) {
      return m("div.wrap", [
        m("h1", "桥梁应变班交台"),
        m(
          "p.sub",
          "测量员提交跨段编号与读数：原始电压按灵敏度系数与额定电压换算成微应变后判定。"
        ),
        m("div.card", [
          m(
            "form",
            {
              onsubmit: async (e) => {
                e.preventDefault();
                state.error = "";
                state.loading = true;
                try {
                  const data = await api("/api/auth/login", {
                    method: "POST",
                    body: JSON.stringify(state.loginForm),
                  });
                  state.token = data.access_token;
                  state.user = { username: data.username, role: data.role };
                  localStorage.setItem(TOKEN_KEY, state.token);
                  localStorage.setItem(USER_KEY, JSON.stringify(state.user));
                  await loadReadings();
                  await loadSettings();
                  startPolling();
                } catch {
                  state.error = "用户名或密码错误";
                } finally {
                  state.loading = false;
                  m.redraw();
                }
              },
            },
            [
              m("div.row", [
                m("label", [
                  "用户名",
                  m("input", {
                    value: state.loginForm.username,
                    oninput: (e) => {
                      state.loginForm.username = e.target.value;
                    },
                  }),
                ]),
                m("label", [
                  "密码",
                  m("input", {
                    type: "password",
                    value: state.loginForm.password,
                    oninput: (e) => {
                      state.loginForm.password = e.target.value;
                    },
                  }),
                ]),
                m("button", { type: "submit", disabled: state.loading }, "登录"),
              ]),
              state.error ? m("p.err", state.error) : null,
            ]
          ),
          m(
            "p.sub",
            { style: { marginBottom: 0 } },
            "测量员 surveyor / surv123456 · 复核员 reviewer / rev123456"
          ),
        ]),
      ]);
    }

    const isWriter = state.user?.role === "writer";

    return m("div.wrap", [
      m("div.topbar", [
        m("div", [
          m("h1", "桥梁应变班交台"),
          m("p.sub", "微应变 80～220 με 为合格，否则为越界。"),
        ]),
        m("div.topright", [
          m("div.nav", [
            m(
              `button${state.view === "home" ? "" : ".secondary"}`,
              {
                type: "button",
                onclick: () => {
                  state.view = "home";
                  loadReadings();
                },
              },
              "班交列表"
            ),
            m(
              `button${state.view === "convert" ? "" : ".secondary"}`,
              {
                type: "button",
                onclick: () => {
                  state.view = "convert";
                  loadSettings();
                  loadConversions();
                },
              },
              "换算专页"
            ),
          ]),
          m("div.userline", [
            `${state.user?.username}（${isWriter ? "测量员" : "复核员"}） `,
            m(
              "button.secondary",
              {
                type: "button",
                onclick: () => {
                  localStorage.removeItem(TOKEN_KEY);
                  localStorage.removeItem(USER_KEY);
                  state.token = "";
                  state.user = null;
                  state.rows = [];
                  state.view = "home";
                  if (state.timer) clearInterval(state.timer);
                  m.redraw();
                },
              },
              "退出"
            ),
          ]),
        ]),
      ]),
      state.view === "convert"
        ? ConvertPage(isWriter)
        : HomeExtra(isWriter),
      ReadingsCard(),
    ]);
  },
};

function HomeExtra(isWriter) {
  if (isWriter) {
    return m("div.card", [
      m("h2", { style: { marginTop: 0, fontSize: "1.05rem" } }, "报送读数"),
      m(
        "p.sub",
        { style: { margin: "0 0 0.5rem" } },
        "原始电压须换算为微应变后参与判定，请到换算专页报送（支持原始电压 / 直填微应变两条路径）。"
      ),
      m(
        "button",
        {
          type: "button",
          onclick: () => {
            state.view = "convert";
            loadSettings();
            loadConversions();
          },
        },
        "前往换算专页"
      ),
    ]);
  }
  return null;
}

function ParamsCard(isWriter) {
  const s = state.settings;
  return m("div.card", [
    m("h2", { style: { marginTop: 0, fontSize: "1.05rem" } }, [
      "换算参数",
      m(
        "span.hint",
        isWriter ? "" : "（复核账号只读，不可修改）"
      ),
    ]),
    m(
      "form",
      {
        onsubmit: async (e) => {
          e.preventDefault();
          state.error = "";
          state.msg = "";
          try {
            const data = await api("/api/settings", {
              method: "PUT",
              body: JSON.stringify({
                sensitivity: state.settingsForm.sensitivity,
                rated_voltage: state.settingsForm.rated_voltage,
              }),
            });
            state.settings = data;
            state.settingsForm.sensitivity = String(data.sensitivity);
            state.settingsForm.rated_voltage = String(data.rated_voltage);
            state.msg = data.message || "换算参数已保存";
            schedulePreview();
          } catch (err) {
            state.error = err.message;
          }
          m.redraw();
        },
      },
      [
        m("div.row", [
          m("label", [
            "灵敏度系数 K",
            m("input", {
              type: "number",
              step: "any",
              min: "0",
              disabled: !isWriter,
              value: state.settingsForm.sensitivity,
              oninput: (e) => {
                state.settingsForm.sensitivity = e.target.value;
              },
            }),
          ]),
          m("label", [
            "额定电压 E（V）",
            m("input", {
              type: "number",
              step: "any",
              min: "0",
              disabled: !isWriter,
              value: state.settingsForm.rated_voltage,
              oninput: (e) => {
                state.settingsForm.rated_voltage = e.target.value;
              },
            }),
          ]),
          isWriter
            ? m("button", { type: "submit" }, "保存参数")
            : null,
        ]),
        s
          ? m(
              "p.sub",
              { style: { margin: "0.5rem 0 0" } },
              `当前生效：K=${fmt(s.sensitivity)}，E=${fmt(s.rated_voltage)} V` +
                `（${s.updated_by || "—"} 更新于 ${s.updated_at ? new Date(s.updated_at).toLocaleString() : "—"}）`
            )
          : null,
        state.error ? m("p.err", state.error) : null,
        state.msg ? m("p.ok", state.msg) : null,
      ]
    ),
  ]);
}

function ConvertPage(isWriter) {
  const f = state.convForm;
  return [
    ParamsCard(isWriter),
    isWriter ? SubmitCard() : null,
    ConversionsCard(),
  ];
}

function pathTab(key, label) {
  const active = state.convForm.path === key;
  return m(
    `button.tab${active ? ".on" : ".secondary"}`,
    {
      type: "button",
      onclick: () => {
        state.convForm.path = key;
        state.preview = null;
        state.previewError = "";
        schedulePreview();
      },
    },
    label
  );
}

function SubmitCard() {
  const f = state.convForm;
  const s = state.settings;
  return m("div.card", [
    m("h2", { style: { marginTop: 0, fontSize: "1.05rem" } }, "双路径报送"),
    m("div.tabs", [pathTab("voltage", "原始电压换算"), pathTab("direct", "直填微应变")]),
    m(
      "form",
      {
        onsubmit: async (e) => {
          e.preventDefault();
          state.error = "";
          state.msg = "";
          state.loading = true;
          const body = { span_code: f.span_code };
          if (f.path === "voltage") body.raw_voltage = f.raw_voltage;
          else body.microstrain = f.microstrain;
          try {
            const data = await api("/api/readings", {
              method: "POST",
              body: JSON.stringify(body),
            });
            state.msg = data.message || "已提交";
            state.convForm = {
              path: f.path,
              span_code: "",
              raw_voltage: "",
              microstrain: "",
            };
            state.preview = null;
            state.previewError = "";
            await Promise.all([loadReadings(), loadConversions()]);
          } catch (err) {
            // 服务端退回措辞与试算预览、直打接口一致，原样展示
            state.error = err.message || "提交失败";
          } finally {
            state.loading = false;
            m.redraw();
          }
        },
      },
      [
        m("div.row", [
          m("label", [
            "跨段编号",
            m("input", {
              required: true,
              placeholder: "例如 跨中S3",
              value: f.span_code,
              oninput: (e) => {
                f.span_code = e.target.value;
              },
            }),
          ]),
          f.path === "voltage"
            ? m("label", [
                "原始电压 U（mV）",
                m("input", {
                  required: true,
                  type: "number",
                  step: "any",
                  placeholder: "例如 1.5",
                  value: f.raw_voltage,
                  oninput: (e) => {
                    f.raw_voltage = e.target.value;
                    schedulePreview();
                  },
                }),
              ])
            : m("label", [
                "微应变（με）",
                m("input", {
                  required: true,
                  type: "number",
                  step: "any",
                  placeholder: "例如 150",
                  value: f.microstrain,
                  oninput: (e) => {
                    f.microstrain = e.target.value;
                    schedulePreview();
                  },
                }),
              ]),
          m("button", { type: "submit", disabled: state.loading }, "报送并入队"),
        ]),
        f.path === "voltage" && s
          ? m(
              "p.sub",
              { style: { margin: "0.4rem 0 0" } },
              `按专页参数换算：ε = U(mV) ÷（K × E）× 1000，当前 K=${fmt(
                s.sensitivity
              )}，E=${fmt(s.rated_voltage)} V`
            )
          : null,
        PreviewBox(),
        state.error ? m("p.err", state.error) : null,
        state.msg ? m("p.ok", state.msg) : null,
      ]
    ),
  ]);
}

function PreviewBox() {
  if (state.previewError) {
    return m("p.err.preview", `试算退回：${state.previewError}`);
  }
  const p = state.preview;
  if (!p) {
    return m("p.sub.preview", "输入数值后自动试算（不入队）。");
  }
  return m("div.preview", [
    m("span", { class: verdictClass(p.verdict, "done") }, p.verdict),
    m(
      "span",
      `换算微应变：${fmt(p.microstrain)} με（${p.reason}）`
    ),
    m("code", p.formula),
  ]);
}

function ConversionsCard() {
  return m("div.card", [
    m("h2", { style: { marginTop: 0, fontSize: "1.05rem" } }, "换算流水"),
    m("table", [
      m("thead", [
        m("tr", [
          m("th", "流水号"),
          m("th", "时间"),
          m("th", "跨段"),
          m("th", "路径"),
          m("th", "原始电压(mV)"),
          m("th", "K"),
          m("th", "E(V)"),
          m("th", "微应变"),
          m("th", "换算公式"),
          m("th", "提交人"),
        ]),
      ]),
      m(
        "tbody",
        state.conversions.length
          ? state.conversions.map((r) =>
              m("tr", { key: r.id }, [
                m("td", r.id),
                m("td", r.created_at ? new Date(r.created_at).toLocaleString() : "—"),
                m("td", r.span_code),
                m("td", r.input_mode === "voltage" ? "电压换算" : "直填"),
                m("td", fmt(r.raw_voltage)),
                m("td", fmt(r.sensitivity)),
                m("td", fmt(r.rated_voltage)),
                m("td", fmt(r.microstrain)),
                m("td", m("code", r.formula || "—")),
                m("td", r.created_by),
              ])
            )
          : [m("tr", m("td", { colspan: 10 }, "暂无换算流水"))]
      ),
    ]),
  ]);
}

function ReadingsCard() {
  return m("div.card", [
    m("h2", { style: { marginTop: 0, fontSize: "1.05rem" } }, "读数列表"),
    m("table", [
      m("thead", [
        m("tr", [
          m("th", "编号"),
          m("th", "跨段"),
          m("th", "路径"),
          m("th", "原始电压(mV)"),
          m("th", "微应变"),
          m("th", "结论"),
          m("th", "说明"),
          m("th", "状态"),
          m("th", "提交人"),
        ]),
      ]),
      m(
        "tbody",
        state.rows.length
          ? state.rows.map((r) =>
              m("tr", { key: r.id }, [
                m("td", r.id),
                m("td", r.span_code),
                m("td", r.input_mode === "voltage" ? "电压换算" : r.input_mode === "direct" ? "直填" : "—"),
                m("td", fmt(r.raw_voltage)),
                m("td", fmt(r.microstrain)),
                m("td", [
                  m("span", { class: verdictClass(r.verdict, r.status) }, displayVerdict(r)),
                ]),
                m("td", r.reason || "—"),
                m("td", r.status),
                m("td", r.created_by),
              ])
            )
          : [m("tr", m("td", { colspan: 9 }, "暂无数据"))]
      ),
    ]),
  ]);
}

export default App;
