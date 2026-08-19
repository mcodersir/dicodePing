using System.Windows.Forms;

namespace WinForms
{
    public partial class Form1 : Form
    {
        public Form1()
        {
            InitializeComponent();
        }

        public void AppendText(string text) =>
          this.textBox1.AppendText(text);
    }
}