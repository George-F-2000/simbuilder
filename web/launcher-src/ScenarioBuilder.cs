using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

// Scenario Builder launcher: opens index.html (next to this exe) in a
// chromeless Edge app window, falling back to the default browser.
static class Launcher
{
    static void Main()
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        string index = Path.Combine(dir, "index.html");

        if (!File.Exists(index))
        {
            MessageBox.Show(
                "index.html not found.\n\nKeep ScenarioBuilder.exe in the same folder as index.html, style.css and app.js.",
                "Scenario Builder", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        string url = new Uri(index).AbsoluteUri;

        string[] edgePaths =
        {
            @"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            @"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
        };

        foreach (string edge in edgePaths)
        {
            if (File.Exists(edge))
            {
                Process.Start(edge, "--app=\"" + url + "\" --window-size=1450,950");
                return;
            }
        }

        // no Edge found: open in whatever the default browser is
        Process.Start(url);
    }
}
