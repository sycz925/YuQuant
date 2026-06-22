import React from 'react'
import { Button, Result } from 'antd'

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex justify-center items-center min-h-[60vh]">
          <Result
            status="error"
            title="页面出错了"
            subTitle={this.state.error?.message || '发生了未知错误'}
            extra={
              <Button type="primary" onClick={this.handleReset}>
                重试
              </Button>
            }
          />
        </div>
      )
    }
    return this.props.children
  }
}

export default ErrorBoundary
