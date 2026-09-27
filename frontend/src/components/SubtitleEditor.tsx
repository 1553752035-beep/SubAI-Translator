export function SubtitleEditor() {
  return (
    <div>
      <div className="table-head">
        <div className="t">字幕编辑器（演示）</div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button className="btn" style={{ padding: '6px 12px', fontSize: '12px' }}>
            导出 SRT
          </button>
          <button className="btn" style={{ padding: '6px 12px', fontSize: '12px' }}>
            导出 JSON
          </button>
        </div>
      </div>

      <div className="table-card">
        <table>
          <thead>
            <tr>
              <th style={{ width: '60px' }}>#</th>
              <th style={{ width: '120px' }}>开始时间</th>
              <th style={{ width: '120px' }}>结束时间</th>
              <th>源文本</th>
              <th>译文</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="idx">1</td>
              <td>00:00:01,000</td>
              <td>00:00:04,000</td>
              <td>Welcome to this tutorial</td>
              <td>欢迎观看本教程</td>
            </tr>
            <tr>
              <td className="idx">2</td>
              <td>00:00:05,000</td>
              <td>00:00:08,000</td>
              <td>Today we will learn about</td>
              <td>今天我们将学习关于</td>
            </tr>
            <tr>
              <td className="idx">3</td>
              <td>00:00:09,000</td>
              <td>00:00:12,000</td>
              <td>subtitle translation</td>
              <td>字幕翻译的内容</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}