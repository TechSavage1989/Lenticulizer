using System;
using System.Drawing;
using System.IO;
using System.Text.Json;
using System.Windows.Forms;

namespace Lenticulizer.Desktop
{
    internal static class AppPreferences
    {
        static string DirectoryPath => Path.Combine(Program.LocalRoot, "Lenticulizer", "Settings");
        static string WindowPath => Path.Combine(DirectoryPath, "window.json");

        internal static void RestoreWindow(Form form)
        {
            try
            {
                if (!File.Exists(WindowPath)) return;
                var value = JsonSerializer.Deserialize<WindowState>(File.ReadAllText(WindowPath));
                if (value == null || value.Width < form.MinimumSize.Width || value.Height < form.MinimumSize.Height) return;
                var bounds = new Rectangle(value.Left, value.Top, value.Width, value.Height);
                bool visible = false;
                foreach (var screen in Screen.AllScreens) if (screen.WorkingArea.IntersectsWith(bounds)) { visible = true; break; }
                if (!visible) return;
                form.StartPosition = FormStartPosition.Manual;
                form.Bounds = bounds;
                if (value.Maximized) form.WindowState = FormWindowState.Maximized;
            }
            catch { }
        }

        internal static void SaveWindow(Form form)
        {
            try
            {
                Directory.CreateDirectory(DirectoryPath);
                Rectangle bounds = form.WindowState == FormWindowState.Normal ? form.Bounds : form.RestoreBounds;
                var value = new WindowState { Left = bounds.Left, Top = bounds.Top, Width = bounds.Width, Height = bounds.Height, Maximized = form.WindowState == FormWindowState.Maximized };
                string temporary = WindowPath + ".tmp";
                File.WriteAllText(temporary, JsonSerializer.Serialize(value));
                File.Move(temporary, WindowPath, true);
            }
            catch { }
        }

        sealed class WindowState
        {
            public int Left { get; set; }
            public int Top { get; set; }
            public int Width { get; set; }
            public int Height { get; set; }
            public bool Maximized { get; set; }
        }
    }
}
