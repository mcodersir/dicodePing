package ir.dicode.ping.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import ir.dicode.ping.data.AppRepository

class MainViewModel(app: Application) : AndroidViewModel(app) { val repo = AppRepository.get(app) }
